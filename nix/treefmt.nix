_: {
  perSystem = _: {
    treefmt.config.programs = {
      alejandra.enable = true;
      deadnix.enable = true;
      prettier.enable = true;
      ruff-check.enable = true;
      ruff-format.enable = true;
      statix.enable = true;
    };
  };
}
