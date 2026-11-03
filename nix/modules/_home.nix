# The Home Manager module. Exported from default.nix; the leading underscore
# keeps import-tree from loading it as a flake-parts module.
self: {
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.programs.freepilot;
  toml = pkgs.formats.toml {};
in {
  options.programs.freepilot = {
    enable = lib.mkEnableOption "freepilot, a DDC/CI monitor control CLI";

    package = lib.mkOption {
      type = lib.types.package;
      default = self.packages.${pkgs.stdenv.hostPlatform.system}.freepilot;
      defaultText = lib.literalExpression "freepilot.packages.\${pkgs.stdenv.hostPlatform.system}.freepilot";
      description = "The freepilot package to install.";
    };

    settings = lib.mkOption {
      inherit (toml) type;
      default = {};
      example = lib.literalExpression ''
        {
          monitors.desk.serial = "ABC123";
          profiles.coding = {
            monitor = "desk";
            picture-mode = "coding-dark";
            brightness = 40;
          };
        }
      '';
      description = ''
        Contents of freepilot's config.toml: monitor aliases and profiles.
        See the freepilot README for the keys.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [cfg.package];
    xdg.configFile."freepilot/config.toml" = lib.mkIf (cfg.settings != {}) {
      source = toml.generate "freepilot-config.toml" cfg.settings;
    };
  };
}
