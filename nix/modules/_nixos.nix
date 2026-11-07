# The NixOS module. Exported from default.nix; the leading underscore keeps
# import-tree from loading it as a flake-parts module.
self: {
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.programs.freepilot;
in {
  options.programs.freepilot = {
    enable = lib.mkEnableOption "freepilot, a DDC/CI monitor control app";

    package = lib.mkOption {
      type = lib.types.package;
      default = self.packages.${pkgs.stdenv.hostPlatform.system}.freepilot;
      defaultText = lib.literalExpression "freepilot.packages.\${pkgs.stdenv.hostPlatform.system}.freepilot";
      description = "The freepilot package to install.";
    };
  };

  # hardware.i2c loads i2c-dev and gives /dev/i2c-* to its group and to
  # local seat users. Adding users to the group is left to the user's
  # config, as with other device groups.
  config = lib.mkIf cfg.enable {
    hardware.i2c.enable = true;
    environment.systemPackages = [cfg.package];
  };
}
