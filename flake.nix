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

          # ---- The modules, booted -------------------------------------------------
          #
          # One VM per module, asserting what a browser or a probe would see through
          # nginx: the SPA shell on a deep link, the API behind its prefix, the health
          # probe, and, where there is a database, that the migration ran. `nix flake
          # check` runs all three; `.github/preflight.json` runs them on a diff that
          # can break them. They need KVM.
          checks = {
            pigrocrm = pkgs.testers.runNixOSTest {
              name = "pigrocrm";
              nodes.machine = {
                imports = [ self.nixosModules.pigrocrm ];
                services.pigrocrm = {
                  enable = true;
                  domain = "pigrocrm.test";
                  # One of each type, so a bool that rendered as `False` (which pydantic
                  # refuses) would fail the boot here rather than on somebody's host.
                  settings = {
                    timezone = "Europe/Rome";
                    mcp_full_access = false;
                    solleciti_grace_days = 7;
                  };
                  # A throwaway secret for a throwaway VM; in the store on purpose,
                  # where a real one must never be.
                  environmentFile = pkgs.writeText "pigrocrm-test.env" ''
                    PIGROCRM_JWT_SECRET=test-only-secret-long-enough-for-the-validator
                  '';
                };
              };
              testScript = ''
                machine.wait_for_unit("pigrocrm-api.service")
                machine.wait_for_open_port(8000)
                machine.wait_for_unit("nginx.service")

                # The probe, through nginx, exact path (spa.conf: not under /api/).
                machine.succeed("curl -fsS http://localhost/health | grep -F '\"status\":\"ok\"'")
                # The SPA shell, on its prefix and on a deep link a refresh would hit.
                machine.succeed("curl -fsS http://localhost/app/ | grep -F '/app/assets/'")
                machine.succeed("curl -fsS http://localhost/app/clienti/some-uuid | grep -F '/app/assets/'")
                machine.succeed("curl -fsS http://localhost/app/mark.svg >/dev/null")
                # The bare root goes into the application, with a relative Location.
                machine.succeed("curl -sS -o /dev/null -w '%{http_code} %{redirect_url}' http://localhost/ | grep -Fx '302 http://localhost/app/'")
                # A space's own prefix reaches the same shell and the same API.
                machine.succeed("curl -fsS http://localhost/studiorossi/app/ | grep -F '/app/assets/'")
                machine.succeed("curl -fsS http://localhost/studiorossi/health | grep -F '\"status\":\"ok\"'")
                # The API answers behind /api/: an unauthenticated request is refused
                # by the application, not by nginx.
                machine.succeed("curl -sS -o /dev/null -w '%{http_code}' http://localhost/api/auth/me | grep -Ex '401'")
                # Nothing else is served: no SPA fallback outside /app/.
                machine.succeed("curl -sS -o /dev/null -w '%{http_code}' http://localhost/nothing/here | grep -Ex '404'")
                # The migration ran against the local database before the API started.
                machine.succeed("su postgres -s /bin/sh -c \"psql -d pigrocrm -tAc 'select version_num from alembic_version'\" | grep -E '.'")
                # A space is a database the API creates: the role may.
                machine.succeed("su postgres -s /bin/sh -c \"psql -tAc \\\"select rolcreatedb from pg_roles where rolname = 'pigrocrm'\\\"\" | grep -Fx 't'")
                # The renderer the unit was pointed at is the pinned pair, and runs as
                # the unit's own user under the same sandbox flags.
                for var, expected in (("PIGROCRM_TYPST_BINARY", "typst ${typstVersion} "), ("PIGROCRM_PANDOC_BINARY", "pandoc ${pandocVersion}")):
                    binary = machine.succeed(f"systemctl show -p Environment pigrocrm-api | grep -oE '{var}=[^ ]+' | cut -d= -f2").strip()
                    out = machine.succeed(f"systemd-run --wait --pipe --uid=pigrocrm -p ProtectSystem=strict -p PrivateDevices=true {binary} --version")
                    assert expected in out, f"{var}: {out!r}"
              '';
            };

            # The hub beside the website on one name, which is joinorbiters.com's own
            # layout: two modules adding locations to the same virtual host.
            hub = pkgs.testers.runNixOSTest {
              name = "hub";
              nodes.machine = {
                imports = [
                  self.nixosModules.orbiters-hub
                  self.nixosModules.orbiters-website
                ];
                services.orbiters-hub = {
                  enable = true;
                  domain = "hub.test";
                };
                services.orbiters-website = {
                  enable = true;
                  domain = "hub.test";
                };
              };
              testScript = ''
                machine.wait_for_unit("orbiters-hub-api.service")
                machine.wait_for_open_port(8000)
                machine.wait_for_unit("nginx.service")

                # The hub's probe touches the database on purpose, so a 200 here is
                # the migration and Postgres both.
                machine.succeed("curl -fsS http://localhost/health | grep -F '\"status\":\"ok\"'")
                machine.succeed("curl -sS -o /dev/null -w '%{http_code} %{redirect_url}' http://localhost/hub | grep -Fx '302 http://localhost/hub/'")
                machine.succeed("curl -fsS http://localhost/hub/ | grep -F '/hub/assets/'")
                machine.succeed("curl -fsS http://localhost/hub/admin/anything | grep -F '/hub/assets/'")
                machine.succeed("curl -fsS http://localhost/hub/mark.svg >/dev/null")
                # The two API prefixes the host routes to the hub reach FastAPI: an
                # empty POST is a 422 with FastAPI's JSON body, which nginx's own
                # errors never are. (`Server:` is no discriminator, nginx rewrites it.)
                machine.succeed("curl -sS -X POST http://localhost/api/hub/companies | grep -F '\"detail\"'")
                machine.succeed("curl -sS -X POST http://localhost/api/orbiters/signups | grep -F '\"detail\"'")
                # The magic link's token travels in the SPA's URL and in no Referer.
                machine.succeed("curl -sS -o /dev/null -D - http://localhost/hub/ | grep -i '^referrer-policy: strict-origin'")
                # The website's front door on the same name, untouched by the hub.
                machine.succeed("curl -fsS http://localhost/ | grep -Fi 'orbiters'")
                machine.succeed("curl -sS -o /dev/null -w '%{http_code}' http://localhost/nothing | grep -Ex '404'")
              '';
            };

            website = pkgs.testers.runNixOSTest {
              name = "website";
              nodes.machine = {
                imports = [ self.nixosModules.orbiters-website ];
                services.orbiters-website = {
                  enable = true;
                  domain = "website.test";
                };
              };
              testScript = ''
                machine.wait_for_unit("nginx.service")
                # The path map of projects/website/deploy/nginx.conf, page by page:
                # the landing at the root, the community page under its name, the
                # old landing address home.
                machine.succeed("curl -fsS http://localhost/ | grep -Fi 'orbiters'")
                machine.succeed("curl -fsS http://localhost/orbiters | grep -Fi 'orbiters'")
                machine.succeed("curl -fsS http://localhost/privacy >/dev/null")
                machine.succeed("curl -fsS http://localhost/termini >/dev/null")
                machine.succeed("curl -fsS http://localhost/pitch >/dev/null")
                machine.succeed("curl -sS -o /dev/null -w '%{http_code} %{redirect_url}' http://localhost/pigrocrm | grep -Fx '301 http://localhost/'")
                # The hashed assets the pages link to are served under /assets/.
                machine.succeed("curl -fsS http://localhost/ | grep -oE '/assets/[^\"]+' | head -1 | xargs -I{} curl -fsS http://localhost{} >/dev/null")
                # No fallback: a file nobody linked is a 404, as is the bare html name.
                machine.succeed("curl -sS -o /dev/null -w '%{http_code}' http://localhost/nothing | grep -Ex '404'")
                machine.succeed("curl -sS -o /dev/null -w '%{http_code}' http://localhost/privacy.html | grep -Ex '404'")
              '';
            };
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

      # ---- Self-hosting: one NixOS module per deployable ---------------------------
      #
      # These are for whoever self-hosts a product under the AGPL, on NixOS. They are
      # not how Orbiters' own environments are deployed, which stays the compose stack
      # and `_deploy-compose.yml` (docs/design/DECISIONS.md, 2026-09-09), so a
      # preview or a production of ours is never brought up from here.
      #
      # Each module reads its compose file and its nginx configuration as the contract
      # and restates them in NixOS terms: the same environment variables, the same
      # locations, the same start-up order (migrate, then serve). Where a location is
      # written twice, here and in `deploy/`, the VM test above is what keeps the two
      # saying the same thing.
      flake.nixosModules =
        let
          # `settings.timezone = "Europe/Rome"` becomes `PIGROCRM_TIMEZONE=Europe/Rome`:
          # the keys are the field names of the project's `Settings` class, which is
          # the one place their meaning is documented.
          settingsToEnv =
            prefix: settings:
            inputs.nixpkgs.lib.mapAttrs' (
              name: value:
              inputs.nixpkgs.lib.nameValuePair "${prefix}${inputs.nixpkgs.lib.toUpper name}" (
                if builtins.isBool value then inputs.nixpkgs.lib.boolToString value else toString value
              )
            ) settings;
          settingsType =
            lib:
            lib.types.attrsOf (
              lib.types.oneOf [
                lib.types.str
                lib.types.bool
                lib.types.int
              ]
            );
          # The systemd sandbox the two APIs share: a static user for the state that
          # must outlive the unit, a read-only view of everything else.
          hardening = {
            NoNewPrivileges = true;
            PrivateTmp = true;
            PrivateDevices = true;
            ProtectSystem = "strict";
            ProtectHome = true;
            ProtectKernelTunables = true;
            ProtectKernelModules = true;
            ProtectControlGroups = true;
            RestrictAddressFamilies = [
              "AF_UNIX"
              "AF_INET"
              "AF_INET6"
            ];
            RestrictNamespaces = true;
            LockPersonality = true;
            RestrictRealtime = true;
            SystemCallArchitectures = "native";
          };
          # A Postgres of the machine's own, reached over the socket as the unit's
          # user, which is what the compose stack's `db` service is here.
          localPostgres = user: {
            services.postgresql = {
              enable = true;
              ensureDatabases = [ user ];
              ensureUsers = [
                {
                  name = user;
                  ensureDBOwnership = true;
                }
              ];
            };
          };
          socketUrl = user: "postgresql+psycopg://${user}@/${user}?host=/run/postgresql";
          proxyLocation = port: {
            proxyPass = "http://127.0.0.1:${toString port}";
          };
        in
        {
          pigrocrm =
            {
              config,
              lib,
              pkgs,
              ...
            }:
            let
              cfg = config.services.pigrocrm;
              own = self.packages.${pkgs.stdenv.hostPlatform.system};
              # Dockerfile.web copies `dist/` to `html/app`: the SPA's assets are
              # absolute under `/app/`, so the document root holds it under that name.
              webRoot = pkgs.runCommand "pigrocrm-web-root" { } ''
                mkdir -p "$out"
                ln -s ${cfg.web} "$out/app"
              '';
              migrate = pkgs.writeShellScript "pigrocrm-migrate" ''
                cd ${cfg.package}/share/pigrocrm-api
                exec ${cfg.package}/bin/alembic upgrade head
              '';
              # The SPA reads a space's prefix from the URL (spa.conf, "Spaces"):
              # `/<slug>/app/...` is the same shell, `/<slug>/api/...` and
              # `/<slug>/health` reach the API with the full path, whose middleware
              # strips the prefix.
              slug = "[a-z0-9][a-z0-9-]{1,30}[a-z0-9]";
            in
            {
              options.services.pigrocrm = {
                enable = lib.mkEnableOption "PigroCRM, the API behind nginx with its SPA";
                package = lib.mkOption {
                  type = lib.types.package;
                  default = own.pigrocrm-api;
                  defaultText = "orbiters.packages.<system>.pigrocrm-api";
                  description = "The API's environment, with Alembic and the migrations under share/.";
                };
                web = lib.mkOption {
                  type = lib.types.package;
                  default = own.pigrocrm-web;
                  defaultText = "orbiters.packages.<system>.pigrocrm-web";
                  description = "The SPA's `dist/`.";
                };
                domain = lib.mkOption {
                  type = lib.types.str;
                  example = "pigro.example.com";
                  description = "The nginx virtual host the CRM answers on. TLS is the host's to add (`enableACME`, `forceSSL`).";
                };
                address = lib.mkOption {
                  type = lib.types.str;
                  default = "127.0.0.1";
                  description = "Where uvicorn listens; nginx is what faces the network.";
                };
                port = lib.mkOption {
                  type = lib.types.port;
                  default = 8000;
                };
                environmentFile = lib.mkOption {
                  type = lib.types.path;
                  example = "/run/secrets/pigrocrm.env";
                  description = ''
                    The secrets, as `PIGROCRM_*=value` lines, never in the store. It must
                    define `PIGROCRM_JWT_SECRET` (32 characters or more); the Google
                    variables and a non-local `PIGROCRM_DATABASE_URL` go here too.
                  '';
                };
                settings = lib.mkOption {
                  type = settingsType lib;
                  default = { };
                  example = {
                    timezone = "Europe/Rome";
                    root_slug = "studiorossi";
                    mcp_full_access = false;
                  };
                  description = "Non-secret settings by their field name in `pigrocrm.core.config.Settings`, exported as `PIGROCRM_<NAME>`.";
                };
                database.createLocally = lib.mkOption {
                  type = lib.types.bool;
                  default = true;
                  description = "Run PostgreSQL on this machine and point the API at it over the socket. Off, `PIGROCRM_DATABASE_URL` must be in the environment file.";
                };
                documentsDir = lib.mkOption {
                  type = lib.types.path;
                  default = "/var/lib/pigrocrm/documents";
                  description = "Where `storage_backend = local` writes the PDFs (the compose stack's `PIGROCRM_DOCUMENTS_DIR`).";
                };
                renderer = {
                  pandoc = lib.mkOption {
                    type = lib.types.package;
                    default = own.pandoc;
                    defaultText = "orbiters.packages.<system>.pandoc";
                    description = "Pinned with the API image; see projects/pigrocrm/Dockerfile.api.";
                  };
                  typst = lib.mkOption {
                    type = lib.types.package;
                    default = own.typst;
                    defaultText = "orbiters.packages.<system>.typst";
                  };
                };
              };

              config = lib.mkIf cfg.enable (
                lib.mkMerge [
                  (lib.mkIf cfg.database.createLocally (localPostgres "pigrocrm"))
                  {
                    # A space is a database of its own, created by the API beside the
                    # root's (`tenants.service.TenantService.provision`), and so is the
                    # registry `pigrocrm_tenants`. The compose stack's user is Postgres'
                    # superuser; here it is a role that may create databases and no more.
                    # `postgresql-setup.service` is where nixpkgs creates the role and
                    # the database (`ensureUsers`); the grant goes on the end of it and
                    # the API waits for it, not merely for the server.
                    systemd.services.postgresql-setup.script = lib.mkIf cfg.database.createLocally (
                      lib.mkAfter ''
                        psql -tAc 'ALTER ROLE pigrocrm CREATEDB'
                      ''
                    );

                    users.users.pigrocrm = {
                      isSystemUser = true;
                      group = "pigrocrm";
                      home = "/var/lib/pigrocrm";
                    };
                    users.groups.pigrocrm = { };

                    systemd.services.pigrocrm-api = {
                      description = "PigroCRM API";
                      wantedBy = [ "multi-user.target" ];
                      after = [
                        "network.target"
                      ]
                      ++ lib.optional cfg.database.createLocally "postgresql-setup.service";
                      requires = lib.optional cfg.database.createLocally "postgresql-setup.service";
                      environment = {
                        PIGROCRM_STORAGE_LOCAL_ROOT = cfg.documentsDir;
                        # `tenants.service.default_alembic_ini` walks up from the package
                        # to a checkout layout that a virtualenv in the store does not
                        # have; this is the setting that exists for exactly that.
                        PIGROCRM_TENANTS_ALEMBIC_INI = "${cfg.package}/share/pigrocrm-api/alembic.ini";
                        PIGROCRM_PANDOC_BINARY = lib.getExe' cfg.renderer.pandoc "pandoc";
                        PIGROCRM_TYPST_BINARY = lib.getExe' cfg.renderer.typst "typst";
                      }
                      // lib.optionalAttrs cfg.database.createLocally {
                        PIGROCRM_DATABASE_URL = socketUrl "pigrocrm";
                      }
                      // settingsToEnv "PIGROCRM_" cfg.settings;
                      serviceConfig = hardening // {
                        User = "pigrocrm";
                        Group = "pigrocrm";
                        EnvironmentFile = cfg.environmentFile;
                        StateDirectory = "pigrocrm";
                        ReadWritePaths = [ cfg.documentsDir ];
                        # Migrations first, then serve: one instance, as in the image.
                        ExecStartPre = migrate;
                        ExecStart = "${cfg.package}/bin/uvicorn pigrocrm_api.main:app --host ${cfg.address} --port ${toString cfg.port}";
                        Restart = "on-failure";
                      };
                    };
                    systemd.tmpfiles.rules = [ "d ${cfg.documentsDir} 0750 pigrocrm pigrocrm -" ];

                    # projects/pigrocrm/deploy/nginx/spa.conf, minus what only exists
                    # because that nginx lives in a container beside a moving `api`.
                    services.nginx = {
                      enable = true;
                      recommendedProxySettings = true;
                      virtualHosts.${cfg.domain} = {
                        root = webRoot;
                        # A relative Location on every redirect: an absolute one drops
                        # a non-default port (measured against the image, spa.conf).
                        extraConfig = "absolute_redirect off;";
                        locations = {
                          "= /".return = "302 /app/";
                          "= /app".return = "302 /app/";
                          "= /login".return = "302 /app/login";
                          "^~ /app/".tryFiles = "$uri /app/index.html";
                          "~ \"^/${slug}/app(/|$)\"".tryFiles = "/app/index.html =404";
                          "~ \"^/${slug}/(api|health)(/|$)\"" = proxyLocation cfg.port;
                          "~ \"^/(${slug})$\"".return = "302 /$1/app/";
                          "/api/" = proxyLocation cfg.port;
                          "= /health" = proxyLocation cfg.port;
                          # Anything else: a 404, never the SPA shell.
                          "/".tryFiles = "$uri =404";
                        };
                      };
                    };
                  }
                ]
              );
            };

          orbiters-hub =
            {
              config,
              lib,
              pkgs,
              ...
            }:
            let
              cfg = config.services.orbiters-hub;
              own = self.packages.${pkgs.stdenv.hostPlatform.system};
              webRoot = pkgs.runCommand "orbiters-hub-web-root" { } ''
                mkdir -p "$out"
                ln -s ${cfg.web} "$out/hub"
              '';
              migrate = pkgs.writeShellScript "orbiters-hub-migrate" ''
                cd ${cfg.package}/share/hub-api
                exec ${cfg.package}/bin/alembic upgrade head
              '';
            in
            {
              options.services.orbiters-hub = {
                enable = lib.mkEnableOption "the Orbiters hub: the signup wizards, the admin area and their API";
                package = lib.mkOption {
                  type = lib.types.package;
                  default = own.hub-api;
                  defaultText = "orbiters.packages.<system>.hub-api";
                };
                web = lib.mkOption {
                  type = lib.types.package;
                  default = own.hub-web;
                  defaultText = "orbiters.packages.<system>.hub-web";
                };
                domain = lib.mkOption {
                  type = lib.types.str;
                  example = "example.com";
                  description = "The virtual host: the SPA under /hub/ and the API under /api/hub/ and /api/orbiters/signups, beside the website when both share a name.";
                };
                address = lib.mkOption {
                  type = lib.types.str;
                  default = "127.0.0.1";
                };
                port = lib.mkOption {
                  type = lib.types.port;
                  default = 8000;
                };
                environmentFile = lib.mkOption {
                  type = lib.types.nullOr lib.types.path;
                  default = null;
                  description = "`ORBITERS_*=value` lines for the secrets: the conversions API key, a non-local database URL.";
                };
                settings = lib.mkOption {
                  type = settingsType lib;
                  default = { };
                  example = {
                    signup_url = "https://example.com/";
                  };
                  description = "Non-secret settings by their field name in `orbiters_core.config.Settings`, exported as `ORBITERS_<NAME>`.";
                };
                database.createLocally = lib.mkOption {
                  type = lib.types.bool;
                  default = true;
                };
              };

              config = lib.mkIf cfg.enable (
                lib.mkMerge [
                  (lib.mkIf cfg.database.createLocally (localPostgres "orbiters"))
                  {
                    users.users.orbiters = {
                      isSystemUser = true;
                      group = "orbiters";
                    };
                    users.groups.orbiters = { };

                    systemd.services.orbiters-hub-api = {
                      description = "Orbiters hub API";
                      wantedBy = [ "multi-user.target" ];
                      after = [
                        "network.target"
                      ]
                      ++ lib.optional cfg.database.createLocally "postgresql-setup.service";
                      requires = lib.optional cfg.database.createLocally "postgresql-setup.service";
                      environment =
                        lib.optionalAttrs cfg.database.createLocally {
                          ORBITERS_DATABASE_URL = socketUrl "orbiters";
                        }
                        // settingsToEnv "ORBITERS_" cfg.settings;
                      serviceConfig = hardening // {
                        User = "orbiters";
                        Group = "orbiters";
                        EnvironmentFile = lib.optional (cfg.environmentFile != null) cfg.environmentFile;
                        ExecStartPre = migrate;
                        ExecStart = "${cfg.package}/bin/uvicorn orbiters_api.main:app --host ${cfg.address} --port ${toString cfg.port}";
                        Restart = "on-failure";
                      };
                    };

                    # projects/hub/deploy/nginx.conf for the SPA, and the two API
                    # locations the host's joinorbiters.conf routes to the hub.
                    services.nginx = {
                      enable = true;
                      recommendedProxySettings = true;
                      virtualHosts.${cfg.domain} = {
                        # No vhost-level `root`: the website's module may share this
                        # name, and every location below names its own.
                        # Only headers at server level: a directive set here twice, by
                        # this module and the website's on the same name, is a
                        # duplicate nginx refuses to start on. `absolute_redirect`
                        # therefore sits on the one location that redirects.
                        extraConfig = ''
                          # The magic link's token is in the SPA's URL and must not
                          # travel in a Referer to anything (deploy/nginx.conf).
                          add_header Referrer-Policy strict-origin always;
                        '';
                        locations = {
                          "= /hub" = {
                            return = "302 /hub/";
                            extraConfig = "absolute_redirect off;";
                          };
                          "^~ /hub/assets/" = {
                            root = webRoot;
                            tryFiles = "$uri =404";
                          };
                          "= /hub/mark.svg" = {
                            root = webRoot;
                            tryFiles = "$uri =404";
                          };
                          "^~ /hub/" = {
                            root = webRoot;
                            tryFiles = "$uri /hub/index.html";
                          };
                          "= /api/orbiters/signups" = proxyLocation cfg.port;
                          "^~ /api/hub/" = proxyLocation cfg.port // {
                            extraConfig = "client_max_body_size 6M;";
                          };
                          "= /health" = proxyLocation cfg.port;
                          "/".return = lib.mkDefault "404";
                        };
                      };
                    };
                  }
                ]
              );
            };

          orbiters-website =
            {
              config,
              lib,
              pkgs,
              ...
            }:
            let
              cfg = config.services.orbiters-website;
              own = self.packages.${pkgs.stdenv.hostPlatform.system};
            in
            {
              options.services.orbiters-website = {
                enable = lib.mkEnableOption "the Orbiters website: four static pages and their assets";
                package = lib.mkOption {
                  type = lib.types.package;
                  default = own.website;
                  defaultText = "orbiters.packages.<system>.website";
                };
                domain = lib.mkOption {
                  type = lib.types.str;
                  example = "example.com";
                };
              };

              # projects/website/deploy/nginx.conf: which extensionless path is which
              # page, and nothing invented. The website's own unit test parses that
              # file's `location =` lines; the VM test walks these.
              config = lib.mkIf cfg.enable {
                services.nginx = {
                  enable = true;
                  virtualHosts.${cfg.domain} = {
                    locations = {
                      # The landing is the front door (ORB-145, 2026-09-11); the
                      # community page keeps its name, and `/pigrocrm` follows it home.
                      "= /" = {
                        root = cfg.package;
                        tryFiles = "/index.html =404";
                      };
                      # A relative Location, on the location itself rather than the
                      # server: the hub's module may share this name (see there).
                      "= /pigrocrm" = {
                        return = "301 /";
                        extraConfig = "absolute_redirect off;";
                      };
                      "= /orbiters" = {
                        root = cfg.package;
                        tryFiles = "/orbiters.html =404";
                      };
                      "= /privacy" = {
                        root = cfg.package;
                        tryFiles = "/privacy.html =404";
                      };
                      "= /termini" = {
                        root = cfg.package;
                        tryFiles = "/termini.html =404";
                      };
                      # The pitch deck, a page shared by link (ORB-153).
                      "= /pitch" = {
                        root = cfg.package;
                        tryFiles = "/pitch.html =404";
                      };
                      "/assets/" = {
                        root = cfg.package;
                        tryFiles = "$uri =404";
                      };
                      "/".return = lib.mkDefault "404";
                    };
                  };
                };
              };
            };
        };
    };
}
