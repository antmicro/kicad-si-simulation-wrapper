from pathlib import Path
import re
from typing import Dict, Annotated
import tempfile
import logging
from multiprocessing import Pool
from functools import partial
import subprocess
import shutil

import typer
import yaml

from si_wrapper.create_settings import Settings
from si_wrapper.kicad2net_img import main as kicad2net
from si_wrapper.generate_slices import setup_logging

app = typer.Typer()
logger = logging.getLogger(__name__)


SVG_GLOW_FILTER = """<defs>
    <!-- a transparent glow that takes on the colour of the object it's applied to -->
    <filter
       id="glow"
        x="-500"
        y="-500"
        width="1000"
        height="1000">
      <feGaussianBlur
         stdDeviation="5"
         result="coloredBlur"
         id="feGaussianBlur2926" />
      <feGaussianBlur
         stdDeviation="2"
         result="coloredBlur2"
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
    from wand.image import Image

    with Image(filename=render_path) as render:
        for svg_name, color in svg_dict.items():
            ifile_path = svg_base_path / (svg_name + ".svg")
            with open(ifile_path) as ifile_fd:
                ifile = ifile_fd.read()
            ofile = ifile.replace("opacity:1", "opacity:0.8")
            ofile = ofile.replace('opacity="1"', 'opacity="0.8"')

            # Replace black color with cyan palette
            ofile = re.sub(r"rgb\(\s*0%?,\s*0%?,\s*0%?\)", rf"{color}", ofile)

            # Add glow filter definition after file header
            ofile = re.sub(r"(<svg .*>)", r"\1\n" + SVG_GLOW_FILTER, ofile, count=1)

            # Remove Edge.Cuts (gerbv is not able to output it as transparent)
            ofile = re.sub(r"<path .*rgb\(100%,\s?100%,\s?100%\).*/>", "", ofile)
            ofile = ofile.replace("stroke:rgb(255,255,255);", "opacity: 0;")
            ofile = ofile.replace("fill:rgb(255,255,255);", "opacity: 0;")

            # Apply filter to group
            group_filter = '<g filter="url(#glow)">'
            if "<g" in ofile:
                ofile = re.sub(r"(<g.*>)", group_filter + r"\1", ofile, count=1)
            else:
                ofile = re.sub(r"</defs>", r"</defs>" + group_filter, ofile, count=1)

            ofile = ofile.replace("</svg>", "</g></svg>")

            with tempfile.NamedTemporaryFile(mode="w+") as temp:
                temp.write(ofile)
                temp.flush()
                mod_svg_file = ifile_path.with_stem(ifile_path.stem + "_glow")
                mod_svg_file.write_text(ofile)

                png_file = ifile_path.with_suffix(".png")
                subprocess.run(
                    ["inkscape", temp.name, "--export-type=png", f"--export-filename={png_file}"], check=True
                )

                with Image(filename=png_file) as overlay:
                    if overlay.height > overlay.width:
                        overlay.rotate(90)
                    scale = min(render.width / overlay.width, render.height / overlay.height)
                    overlay.resize(int(overlay.width * scale), int(overlay.height * scale))
                    render.composite(overlay, gravity="center")
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
    pcb = next(Path.cwd().glob("*.kicad_pcb"))
    subprocess.run(
        [
            "kicad-cli",
            "pcb",
            "export",
            "gerbers",
            pcb,
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
        ["kicad-cli", "pcb", "export", "drill", "--drill-origin", "absolute", pcb, "-o", "fab/", "--format", "gerber"]
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
    net_dir = Path.cwd() / "release" / "assets" / "si" / net_name
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
    """Prepare PCB renders for each of the highlighted traces to be simulated."""
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
