_: {
  perSystem = {pkgs, ...}: {
    devShells.default = pkgs.mkShell {
      packages = [
        pkgs.ddcutil
        pkgs.git
        pkgs.nixd
        pkgs.python3
        pkgs.uv
      ];
      env = {
        UV_PYTHON = pkgs.python3.interpreter;
        UV_PYTHON_DOWNLOADS = "never";
      };
    };
  };
}
