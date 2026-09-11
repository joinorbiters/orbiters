{
  description = "Orbiters monorepo: development shell, packages, NixOS modules and their tests";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
    flake-parts.inputs.nixpkgs-lib.follows = "nixpkgs";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    inputs@{
      self,
      flake-parts,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
      ...
    }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      # The two renderer binaries below are fetched as the upstream x86_64 Linux
      # releases, so that is the one system this shell is known to work on. Another
      # system needs its own tarball and hash in the two derivations, nothing else.
      systems = [ "x86_64-linux" ];

      perSystem =
        {
          pkgs,
          lib,
          ...
        }:
        let
          # One capture group out of a file, with the file named in the error when the
          # pin moved to a shape this regex does not read.
          readPin =
            file: regex:
            let
              m = builtins.match regex (builtins.readFile file);
            in
            if m == null then throw "flake.nix: no version found in ${toString file}" else lib.head m;

          # `.python-version` holds "3.13"; the attribute is `python313`.
          pythonVersion = readPin ./.python-version "([0-9]+\\.[0-9]+)[[:space:]]*";
          python = pkgs."python${lib.replaceStrings [ "." ] [ "" ] pythonVersion}";

          # `engines.node` is ">=22"; the attribute is `nodejs_22`.
          nodeMajor = lib.head (
            builtins.match ">=([0-9]+)" (builtins.fromJSON (builtins.readFile ./package.json)).engines.node
          );
          nodejs = pkgs."nodejs_${nodeMajor}";

          # PigroCRM's document renderer is verified against exactly the pair the
          # Dockerfile installs (and `_python-gate.yml` repeats): Typst's diagnostic
          # format and the auto-typography workaround were both confirmed against
          # 0.14.2 specifically. nixpkgs carries 0.15.1 and pandoc 3.7.0.2 today, so
          # `pkgs.typst` and `pkgs.pandoc` would hand a developer a renderer that
          # proves less than nothing. These are the same release tarballs the
          # Dockerfile downloads, and both binaries are statically linked, so they run
          # unpatched.
          dockerfileArg = name: readPin ./projects/pigrocrm/Dockerfile.api ".*\nARG ${name}=([^\n]+)\n.*";
          pandocVersion = dockerfileArg "PANDOC_VERSION";
          typstVersion = dockerfileArg "TYPST_VERSION";

          pandoc = pkgs.stdenvNoCC.mkDerivation {
            pname = "pandoc-bin";
            version = pandocVersion;
            src = pkgs.fetchurl {
              url = "https://github.com/jgm/pandoc/releases/download/${pandocVersion}/pandoc-${pandocVersion}-linux-amd64.tar.gz";
              hash = "sha256-s2KBXiHYrTYpwSSqkrr1RVjaCGrXI3S09v3Ze58ydbA=";
            };
            dontBuild = true;
            installPhase = ''
              install -Dm755 bin/pandoc "$out/bin/pandoc"
            '';
            doInstallCheck = true;
            installCheckPhase = ''
              "$out/bin/pandoc" --version | head -1 | grep -Fx "pandoc ${pandocVersion}"
            '';
          };

          typst = pkgs.stdenvNoCC.mkDerivation {
            pname = "typst-bin";
            version = typstVersion;
            src = pkgs.fetchurl {
              url = "https://github.com/typst/typst/releases/download/v${typstVersion}/typst-x86_64-unknown-linux-musl.tar.xz";
              hash = "sha256-pgRMutKpVN65IRZ+JX4SCsChayAznsARIRlP+dOUmW0=";
            };
            dontBuild = true;
            installPhase = ''
              install -Dm755 typst "$out/bin/typst"
            '';
            doInstallCheck = true;
            installCheckPhase = ''
              "$out/bin/typst" --version | grep -F "typst ${typstVersion} "
            '';
          };

          # ---- Python: the uv workspace, built from uv.lock -------------------------
          #
          # `sourcePreference = "wheel"`: the same artefacts uv installs into the
          # Docker images, patched for the Nix store rather than rebuilt from sdists.
          # A member of the workspace is a package of this set like any other, so a
          # virtualenv is asked for by the member names an image would `--package`.
          workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };
          pythonSet = (pkgs.callPackage pyproject-nix.build.packages { inherit python; }).overrideScope (
            lib.composeManyExtensions [
              pyproject-build-systems.overlays.default
              (workspace.mkPyprojectOverlay { sourcePreference = "wheel"; })
            ]
          );

          # A Python deployable: the virtualenv of the named workspace members, plus
          # `share/<name>/` holding the Alembic configuration and migrations, which
          # live beside the package in the checkout and inside the images
          # (`packages/core/alembic.ini`, `%(here)s/migrations`) and are not part of
          # any wheel. A module migrates by running `alembic upgrade head` from that
          # directory, which is what both Dockerfiles do on start-up.
          pythonApp =
            {
              name,
              members,
              core,
            }:
            pkgs.symlinkJoin {
              inherit name;
              paths = [
                (pythonSet.mkVirtualEnv "${name}-env" (lib.genAttrs members (_: [ ])))
                (pkgs.runCommand "${name}-migrations" { } ''
                  mkdir -p "$out/share/${name}"
                  cp -r ${core}/alembic.ini ${core}/migrations "$out/share/${name}/"
                '')
              ];
            };

          # ---- Node: the pnpm workspace, built from pnpm-lock.yaml -----------------
          #
          # One dependency store for the whole workspace, fetched once and shared by
          # every Vite build below; its input is exactly what `pnpm install` reads
          # (the three workspace files and every package.json), so a source change
          # does not refetch it. `hash` is the one value in this file that has to be
          # updated by hand: every change to pnpm-lock.yaml changes it, the build
          # fails naming the hash it got, and that hash goes here.
          pnpmDeps = pkgs.fetchPnpmDeps {
            pname = "orbiters-pnpm-deps";
            version = "0";
            fetcherVersion = 4;
            src = lib.fileset.toSource {
              root = ./.;
              fileset = lib.fileset.unions [
                ./package.json
                ./pnpm-workspace.yaml
                ./pnpm-lock.yaml
                (lib.fileset.fileFilter (f: f.name == "package.json") ./projects)
                (lib.fileset.fileFilter (f: f.name == "package.json") ./shared)
              ];
            };
            hash = "sha256-zrY3YcbIYYaWv+Q172besqRt2FhQuh0Ep0OacbKQYhY=";
          };

          # A Vite deployable: the `dist/` of one workspace package, built the way its
          # Dockerfile builds it (`pnpm install --filter <name>...`, then `pnpm --filter
          # <name> build`) from the same files that Dockerfile copies.
          viteApp =
            {
              name,
              dir,
            }:
            let
              manifest = builtins.fromJSON (builtins.readFile (dir + "/package.json"));
            in
            pkgs.stdenv.mkDerivation {
              pname = manifest.name;
              inherit (manifest) version;
              src = lib.fileset.toSource {
                root = ./.;
                fileset = lib.fileset.unions [
                  ./package.json
                  ./pnpm-workspace.yaml
                  ./pnpm-lock.yaml
                  ./shared/brand
                  dir
                ];
              };
              nativeBuildInputs = [
                nodejs
                pkgs.pnpm
                pkgs.pnpmConfigHook
              ];
              inherit pnpmDeps;
              pnpmWorkspaces = [ "${name}..." ];
              buildPhase = ''
                runHook preBuild
                pnpm --filter ${name} build
                runHook postBuild
              '';
              installPhase = ''
                runHook preInstall
                cp -r ${lib.path.removePrefix ./. dir}/dist "$out"
                runHook postInstall
              '';
            };
        in
        {
          packages = {
            pigrocrm-api = pythonApp {
              name = "pigrocrm-api";
              # The MCP server ships inside the API's environment, on demand over
              # stdio, exactly as it does in the image: `python -m pigrocrm_mcp`.
              members = [
                "pigrocrm-api"
                "pigrocrm-mcp"
              ];
              core = ./projects/pigrocrm/packages/core;
            };
            hub-api = pythonApp {
              name = "hub-api";
              members = [
                "orbiters-api"
                "orbiters-mcp"
              ];
              core = ./projects/hub/packages/core;
            };
            pigrocrm-web = viteApp {
              name = "web";
              dir = ./projects/pigrocrm/apps/web;
            };
            hub-web = viteApp {
              name = "hub";
              dir = ./projects/hub/apps/web;
            };
            website = viteApp {
              name = "website";
              dir = ./projects/website;
            };
            # The renderer pair, exported so the PigroCRM module can hand the API the
            # same binaries the image and the shell carry.
            inherit pandoc typst;
          };

          devShells.default = pkgs.mkShell {
            packages = [
              # The two package managers. uv's own version is not load-bearing: every
              # command in this repository runs `--frozen` against uv.lock. pnpm's is
              # not either, since pnpm 10+ reads `packageManager` from package.json
              # and switches itself to the pinned version on first use.
              pkgs.uv
              pkgs.pnpm
              nodejs
              python

              pandoc
              typst
              # `pdftotext`: how the suite reads a rendered PDF back. Test equipment,
              # never part of the product, so the distribution version is fine. Same
              # for `strings`, which one template test runs over a PDF: mkShell's own
              # stdenv happens to put it on PATH, and this line is so nobody depends
              # on that happening.
              pkgs.poppler-utils
              pkgs.binutils
            ];

            # uv would otherwise download a python-build-standalone interpreter, which
            # expects /lib64/ld-linux-x86-64.so.2 and does not start on NixOS. Point it
            # at the interpreter above and refuse the download outright, so the failure
            # mode on a bad `.python-version` is an error rather than a silent fetch.
            UV_PYTHON = lib.getExe python;
            UV_PYTHON_DOWNLOADS = "never";

            # The manylinux wheels in uv.lock (lxml, psycopg's binary build, pydantic-core)
            # bundle their own libraries but leave libstdc++ and zlib to the system, as
            # the manylinux policy allows. NixOS has no system libraries on a global
            # path, so the two are put on the loader's path for this shell only.
            LD_LIBRARY_PATH = lib.makeLibraryPath [
              pkgs.stdenv.cc.cc.lib
              pkgs.zlib
            ];
          };
        };

    };
}
