# Checks for the NixOS and Home Manager modules.
{self, ...}: {
  perSystem = {
    config,
    lib,
    pkgs,
    system,
    ...
  }: let
    freepilot = config.packages.freepilot;

    # Evaluate the Home Manager module against the two options it sets, so
    # the check needs no home-manager input.
    evalHome = settings:
      (lib.evalModules {
        modules = [
          self.homeModules.default
          {
            options.home.packages = lib.mkOption {
              type = lib.types.listOf lib.types.package;
              default = [];
            };
            options.xdg.configFile = lib.mkOption {
              type = lib.types.attrsOf (lib.types.submodule {
                options.source = lib.mkOption {type = lib.types.path;};
              });
              default = {};
            };
            config._module.args.pkgs = pkgs;
          }
          {programs.freepilot = {enable = true;} // settings;}
        ];
      }).config;

    home = evalHome {
      settings = {
        monitors.desk.serial = "ABC123";
        profiles.coding = {
          monitor = "desk";
          picture-mode = "coding-dark";
          brightness = 40;
          vcp."0xd1" = 2;
        };
      };
    };
    homeWithoutSettings = evalHome {};
  in {
    checks =
      {
        # The generated config.toml must load, and the module must add the
        # package and leave config.toml alone when settings are empty.
        freepilot-home-module = assert home.home.packages == [freepilot];
        assert homeWithoutSettings.xdg.configFile == {};
          pkgs.runCommand "freepilot-home-module" {} ''
            export FREEPILOT_CONFIG=${home.xdg.configFile."freepilot/config.toml".source}
            ${lib.getExe freepilot} profile show coding | tee "$out"
            grep -q 'vcp 0xd1 = 2' "$out"
          '';
      }
      // lib.optionalAttrs (system == "x86_64-linux") {
        freepilot-nixos-module = pkgs.testers.runNixOSTest {
          name = "freepilot-nixos-module";
          nodes.machine = {config, ...}: {
            imports = [self.nixosModules.default];
            programs.freepilot.enable = true;
            # i2c-stub gives the VM an i2c bus. It speaks SMBus, not DDC/CI,
            # so this tests permissions and error handling, not the protocol.
            boot.kernelModules = ["i2c-stub"];
            boot.extraModprobeConfig = "options i2c-stub chip_addr=0x37";
            users.users.alice = {
              isNormalUser = true;
              extraGroups = [config.hardware.i2c.group];
            };
          };
          testScript = ''
            machine.wait_for_unit("multi-user.target")
            bus = machine.succeed(
                "grep -l 'SMBus stub' /sys/bus/i2c/devices/i2c-*/name"
                " | head -1 | xargs dirname | xargs basename"
            ).strip()
            machine.succeed(f"test -c /dev/{bus}")
            machine.succeed(f"stat -c %G /dev/{bus} | grep -qx i2c")

            def alice(command):
                return f"su - alice -c '{command}'"

            machine.succeed(alice(f"test -r /dev/{bus} -a -w /dev/{bus}"))
            machine.succeed(alice("freepilot list"))
            machine.succeed(alice("freepilot codes"))

            # The stub can't answer DDC/CI, so this must fail with a
            # message, not a traceback.
            number = bus.removeprefix("i2c-")
            output = machine.fail(
                alice(f"freepilot --transport i2c --bus {number} get brightness 2>&1")
            )
            assert "freepilot:" in output, output
            assert "Traceback" not in output, output
          '';
        };
      };
  };
}
