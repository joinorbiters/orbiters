{
  description = "Orbiters monorepo: the development shell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
    flake-parts.inputs.nixpkgs-lib.follows = "nixpkgs";
  };

  outputs =
    inputs@{ flake-parts, ... }:
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
        in
        {
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
