from pathlib import Path
import re
from typing import Dict, Annotated
import tempfile
import logging
from multiprocessing import Pool
from functools import partial
import subprocess
import shutil

from wand.image import Image, Color
import typer
import yaml

from si_wrapper.create_settings import Settings
from si_wrapper.kicad2net_img import main as kicad2net
from si_wrapper.generate_slices import setup_logging

app = typer.Typer()
logger = logging.getLogger(__name__)


SVG_GLOW_FILTER = """<defs>
    <!-- a transparent glow that takes on the colour of the object it's applied to -->
    <!-- a transparent glow that takes on the colour of the object it's applied to -->
    <filter
       id="glow">
      <feGaussianBlur
         stdDeviation="5"
         result="coloredBlur"
         width="100"
         height="100"
         filterUnits="userSpaceOnUse"
         id="feGaussianBlur2926" />
      <feGaussianBlur
         stdDeviation="2"
         result="coloredBlur2"
         width="60"
         height="60"
         filterUnits="userSpaceOnUse"
         id="feGaussianBlur2927" />
      <feMerge
         id="feMerge2932">
        <feMergeNode
           in="coloredBlur"
           id="feMergeNode2928" />
        <feMergeNode
           in="coloredBlur2"
           id="feMergeNode2929" />
        <feMergeNode
           in="SourceGraphic"
           id="feMergeNode2930" />
      </feMerge>
    </filter>
</defs>"""


def overlay_render(render_path: Path, svg_base_path: Path, out_path: Path, svg_dict: Dict[str, str]) -> None:
    with Image(filename=render_path) as render:
        for svg_name, color in svg_dict.items():
            ifile_path = svg_base_path / (svg_name + ".svg")
            with open(ifile_path) as ifile_fd:
                ifile = ifile_fd.read()
            ofile = ifile.replace("opacity:1", "opacity:0.8")

            # Remove individual colors so they will not interfere with group settings
            ofile = ofile.replace("stroke:rgb(0%,0%,0%)", "")
            ofile = ofile.replace("fill:rgb(0%,0%,0%)", "")

            # Add glow filter definition after file header
            ofile = re.sub(r"(<svg .*>)", r"\1\n" + SVG_GLOW_FILTER, ofile, count=1)

            # Remove Edge.Cuts (gerbv is not able to output it as transparent)
            ofile = re.sub(r"<path .*rgb\(100%,100%,100%\).*/>", "", ofile)

            # Apply filter & color to group
            ofile = ofile.replace("<g ", f'<g filter="url(#glow)" fill="{color}" stroke="{color}" ')

            with tempfile.NamedTemporaryFile(mode="w+") as temp:
                temp.write(ofile)
                temp.flush()
                with Image(filename=temp.name, background=Color("transparent")) as svg_overlay:
                    svg_overlay.resize(render.width, render.height)
                    render.composite(svg_overlay, gravity="center")
        logger.info(f"Save overlay render: {out_path}")
        render.save(filename=out_path)


def prepare_render() -> None:

    pcb_ortho_cfg = {
        "default": {
            "CAMERAS": {"TOP": True},
            "POSITIONS": {"TOP": True},
            "BACKGROUNDS": {"LIST": ["transparent"]},
            "OUTPUTS": [{"STATIC": {}}],
            "SETTINGS": {"RENDER_DIR": "renders", "IMAGE_FORMAT": ["WEBP"]},
            "RENDERER": {"SAMPLES": 32, "IMAGE_WIDTH": 1920, "IMAGE_HEIGHT": 1920},
            "SCENE": {"DEPTH_OF_FIELD": False, "ZOOM_OUT": 1.05, "ADJUST_POS": True, "ORTHO_CAM": True},
        }
    }
    subprocess.run(
        [
            "kicad-cli",
            "pcb",
            "export",
            "gerbers",
            "*.kicad_pcb",
            "-o",
            "fab/",
            "--layers",
            "--precision",
            "6",
            "--subtract-soldermask",
            "--no-protel-ext",
        ]
    )
    subprocess.run(
        [
            "kicad-cli",
            "pcb",
            "export",
            "drill",
            "--drill-origin",
            "absolute",
            "*.kicad_pcb",
            "-o",
            "fab/",
            "--format",
            "gerber",
        ]
    )
    try:
        if Path("blendcfg.yaml").exists():
            shutil.move("blendcfg.yaml", "blendcfg.yaml.bak")
        with open("blendcfg.yaml", mode="a") as f:
            f.write(yaml.dump(pcb_ortho_cfg))
        subprocess.run(["gerber2blend"])
        subprocess.run(["pcbooth"])
    finally:
        if Path("blendcfg.yaml.bak").exists():
            shutil.move("blendcfg.yaml.bak", "blendcfg.yaml")


def process_net(cfile: Path, debug: bool) -> None:

    # Plot net highlight overlay over render
    settings_path = str(cfile)
    settings = Settings(settings_path)

    nets = settings.get_nets()
    net_name = Settings.get_filesystem_name(nets)

    object_namelist = {"B_Cu": "#00AAAA", "In_Cu": "#00CCCC", "F_Cu": "#00EEEE"}
    net_dir = Path.cwd() / "release" / "si-assets" / net_name
    overlay_render(
        render_path=Path.cwd() / "renders" / "topT_transparent.webp",
        svg_base_path=net_dir,
        out_path=net_dir / "top_view.webp",
        svg_dict=object_namelist,
    )


@app.command("overlay_render")
def main(
    config_file: Annotated[Path, typer.Option("--file", "-f", help="Path to settings file")] = Path("si-wrapper-cfg"),
    debug: Annotated[bool, typer.Option("--debug", help="Increase logs verbosity")] = False,
) -> None:
    setup_logging(debug)

    # Create SVG images each with single net
    kicad2net(config_file, debug, no_png=True)

    # Prepare base render
    prepare_render()

    cfg_files = [config_file] if config_file.suffix == ".json" else list(config_file.glob("**/*.json"))
    with Pool() as p:
        p.map(partial(process_net, debug=debug), cfg_files)


if __name__ == "__main__":
    app()
