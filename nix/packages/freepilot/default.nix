{
  inputs,
  lib,
  ...
}: {
  perSystem = {
    config,
    pkgs,
    ...
  }: let
    workspace = inputs.uv2nix.lib.workspace.loadWorkspace {workspaceRoot = ../../..;};
    pythonSet =
      (pkgs.callPackage inputs.pyproject-nix.build.packages {python = pkgs.python3;}).overrideScope
      (lib.composeManyExtensions [
        inputs.pyproject-build-systems.overlays.wheel
        (workspace.mkPyprojectOverlay {sourcePreference = "wheel";})
      ]);
    venv = pythonSet.mkVirtualEnv "freepilot-env" workspace.deps.default;
    devVenv = pythonSet.mkVirtualEnv "freepilot-dev-env" workspace.deps.all;
  in {
    packages = {
      default = config.packages.freepilot;

      freepilot =
        pkgs.runCommand "freepilot-${pythonSet.freepilot.version}" {
          nativeBuildInputs = [pkgs.makeWrapper];
          meta = {
            description = "Control BenQ RD series monitors from Linux over DDC/CI";
            homepage = "https://github.com/alyraffauf/freepilot";
            license = lib.licenses.mit;
            platforms = lib.platforms.linux;
            mainProgram = "freepilot";
          };
        } ''
          makeWrapper ${venv}/bin/freepilot "$out/bin/freepilot" \
            --prefix PATH : ${lib.makeBinPath [pkgs.ddcutil]}
        '';
    };

    checks = {
      freepilot-pytest = pkgs.runCommand "freepilot-pytest" {nativeBuildInputs = [devVenv];} ''
        cd ${../../..}
        pytest -p no:cacheprovider
        touch "$out"
      '';

      freepilot-ty = pkgs.runCommand "freepilot-ty" {nativeBuildInputs = [devVenv];} ''
        cd ${../../..}
        ty check --python ${devVenv}/bin/python
        touch "$out"
      '';
    };
  };
}
