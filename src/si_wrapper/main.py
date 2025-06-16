"""si_wrapper entry point."""

import typer

from si_wrapper import gerber2png, generate_slices, create_settings, renumerator

app = typer.Typer(no_args_is_help=True, add_completion=False)
app.registered_commands += generate_slices.app.registered_commands
app.registered_commands += gerber2png.app.registered_commands
app.registered_commands += create_settings.app.registered_commands
app.registered_commands += renumerator.app.registered_commands

if __name__ == "__main__":
    app()
