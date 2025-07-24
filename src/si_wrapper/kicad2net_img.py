"""Script that creates separate image for each designated net in kicad_pcb."""

import logging
import os
import subprocess
import sys
from typing import Annotated
from pathlib import Path
from si_wrapper.pcbslicer import PCBSlice
from si_wrapper.generate_slices import get_pcb_path, setup_logging, Settings
from si_wrapper.gerber2png import process_gbrs
import tempfile
import typer

logger = logging.getLogger(__name__)
app = typer.Typer()


@app.command("kicad2net_img")
def main(
    config_file: Annotated[Path, typer.Option("--file", "-f", help="Path to settings file")] = Path("si-wrapper-cfg"),
    debug: Annotated[bool, typer.Option("--debug", help="Increase logs verbosity")] = False,
    no_strip: Annotated[bool, typer.Option("--no-strip", help="Do not modify pcb prior to image export")] = False,
    no_png: Annotated[bool, typer.Option("--no-png", help="Skip export to png")] = False,
) -> None:
    """Process gerbers/kicad_pcb to png/svg, optionally striping all but designated net."""
    setup_logging(debug)
    pcb_path = get_pcb_path()
    if pcb_path is None:
        logger.error("No .kicad_pcb file in current directory.")
        sys.exit()

    cfg_files = [config_file] if config_file.suffix == ".json" else list(config_file.glob("**/*.json"))
    cwd = os.getcwd()
    for cfile in cfg_files:
        settings_path = str(cfile)
        settings = Settings(settings_path)

        nets = settings.get_nets()
        net_name = Settings.get_filesystem_name(nets)
        pcb_slice = PCBSlice(pcb_path, nets)
        if not no_strip:
            pcb_slice.purge_all_but_designated()
        with tempfile.TemporaryDirectory() as temp:
            stripped_pcb = (Path(temp) / net_name).with_suffix(".kicad_pcb")
            pcb_slice.save_slice(str(stripped_pcb))
            os.chdir(temp)
            cmd = [
                "kicad-cli",
                "pcb",
                "export",
                "gerbers",
                str(stripped_pcb),
                "-o",
                "./fab",
                "--layers",
                "--precision",
                "6",
                "--subtract-soldermask",
                "--no-protel-ext",
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            process_gbrs(Path(cwd) / "release" / "assets" / "si" / net_name, no_png)
            os.chdir(cwd)


if __name__ == "__main__":
    app()
