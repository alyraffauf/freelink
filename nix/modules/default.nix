{self, ...}: {
  flake = {
    nixosModules.default = import ./_nixos.nix self;
    homeModules.default = import ./_home.nix self;
  };
}
