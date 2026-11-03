_: {
  perSystem = {pkgs, ...}: {
    devShells.default = pkgs.mkShell {
      packages = [
        pkgs.ddcutil
        pkgs.git
        pkgs.nixd
        pkgs.python315
        pkgs.uv
      ];
      env = {
        UV_PYTHON = pkgs.python315.interpreter;
        UV_PYTHON_DOWNLOADS = "never";
      };
    };
  };
}
