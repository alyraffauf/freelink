{lib, ...}: {
  perSystem = {
    config,
    pkgs,
    ...
  }: let
    runtimeLibraries = with pkgs; [wayland libxkbcommon vulkan-loader libGL libxcb libX11 libXi libXcursor libXrandr];
  in {
    packages.default = config.packages.freepilot;
    packages.freepilot = pkgs.rustPlatform.buildRustPackage {
      pname = "freepilot";
      version = (lib.importTOML ../../../Cargo.toml).package.version;
      src = lib.fileset.toSource {
        root = ../../..;
        fileset = lib.fileset.unions [
          ../../../Cargo.toml
          ../../../Cargo.lock
          ../../../src
          ../../../tests
          ../../../assets
        ];
      };
      cargoLock.lockFile = ../../../Cargo.lock;
      nativeBuildInputs = with pkgs; [pkg-config cmake makeWrapper];
      buildInputs = runtimeLibraries ++ (with pkgs; [fontconfig freetype]);
      postFixup = ''
        wrapProgram $out/bin/freepilot \
          --prefix PATH : ${lib.makeBinPath [pkgs.ddcutil]} \
          --prefix LD_LIBRARY_PATH : ${lib.makeLibraryPath runtimeLibraries}
      '';
      postInstall = ''
        install -Dm644 assets/freepilot.desktop $out/share/applications/freepilot.desktop
      '';
      meta = {
        description = "Control monitors over DDC/CI with a CLI and GPUI desktop app";
        license = lib.licenses.mit;
        platforms = lib.platforms.linux;
        mainProgram = "freepilot";
      };
    };
    devShells.default = pkgs.mkShell {
      inputsFrom = [config.packages.freepilot];
      packages = with pkgs; [cargo rustc rustfmt clippy ddcutil nixd];
      LD_LIBRARY_PATH = lib.makeLibraryPath runtimeLibraries;
    };
  };
}
