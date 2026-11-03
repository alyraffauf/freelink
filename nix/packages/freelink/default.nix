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
    venv = pythonSet.mkVirtualEnv "freelink-env" workspace.deps.default;
    devVenv = pythonSet.mkVirtualEnv "freelink-dev-env" workspace.deps.all;
  in {
    packages = {
      default = config.packages.freelink;

      freelink =
        pkgs.runCommand "freelink-${pythonSet.freelink.version}" {
          nativeBuildInputs = [pkgs.makeWrapper];
          meta = {
            description = "Control BenQ RD series monitors from Linux over DDC/CI";
            homepage = "https://github.com/alyraffauf/freelink";
            license = lib.licenses.mit;
            platforms = lib.platforms.linux;
            mainProgram = "freelink";
          };
        } ''
          makeWrapper ${venv}/bin/freelink "$out/bin/freelink" \
            --prefix PATH : ${lib.makeBinPath [pkgs.ddcutil]}
        '';
    };

    checks = {
      freelink-pytest = pkgs.runCommand "freelink-pytest" {nativeBuildInputs = [devVenv];} ''
        cd ${../../..}
        pytest -p no:cacheprovider
        touch "$out"
      '';

      freelink-ty = pkgs.runCommand "freelink-ty" {nativeBuildInputs = [devVenv];} ''
        cd ${../../..}
        ty check --python ${devVenv}/bin/python
        touch "$out"
      '';
    };
  };
}
