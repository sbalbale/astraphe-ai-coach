/** Open state of the ⌘K "Search or ask" palette (wide layouts). */
class CommandPaletteState {
  open = $state(false);
  show() {
    this.open = true;
  }
  hide() {
    this.open = false;
  }
  toggle() {
    this.open = !this.open;
  }
}

export const commandPalette = new CommandPaletteState();
