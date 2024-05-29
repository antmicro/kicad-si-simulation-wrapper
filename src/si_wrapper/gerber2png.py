"""Script that creates bitmaps from gerbers."""

import logging
import subprocess
import PIL.Image
import PIL.ImageOps
import os
import sys

logger = logging.getLogger(__name__)


def process_gbrs_to_pngs() -> None:
    """Process all gerber files to PNG's.

    Finds edge cuts gerber as well as copper gerbers in `fab` directory.
    Processes copper gerbers into PNG's using edge_cuts for framing.
    """
    img_dir = "."

    if not os.path.exists(img_dir):
        os.makedirs(img_dir)

    files = os.listdir(os.path.join(os.getcwd(), "fab"))
    edge = next(filter(lambda name: "Edge_Cuts.gbr" in name, files), None)
    if edge is None:
        logger.error("No edge_cuts gerber found")
        sys.exit(1)

    layers = [
        list(filter(lambda name: "F_Cu.gbr" in name, files))[0],
        list(filter(lambda name: "B_Cu.gbr" in name, files))[0],
    ]
    layers_in = list(filter(lambda name: "-In" in name, files))

    if len(layers) == 0:
        logger.warning("No copper gerbers found")

    # Split top and bootom into two images
    for name in layers:
        output = name.split("-")[-1].split(".")[0] + ".png"
        fb_gbr2png(
            os.path.join(os.getcwd(), "fab", name),
            os.path.join(os.getcwd(), "fab", edge),
            os.path.join(os.getcwd(), img_dir, output),
        )

    # Reduce inner layers to one image
    output = "In_Cu.png"
    in_gbr2png(
        [os.path.join(os.getcwd(), "fab", name) for name in layers_in],
        os.path.join(os.getcwd(), "fab", edge),
        os.path.join(os.getcwd(), img_dir, output),
    )


def in_gbr2png(gerber_filenames: list[str], edge_filename: str, output_filename: str) -> None:
    """Generate PNG from gerber file.

    Generates PNG of a gerber using gerbv and convert.
    Edge cuts gerber is used to crop the image correctly.
    """
    dpi = 1000

    not_cropped_name = f"{output_filename.split('.')[0]}_not_cropped.png"
    foreground_array = [" --foreground=#ffffff"] * len(gerber_filenames)
    foreground_array.append(" --foreground=#0000ff")

    gerbv_command = f'gerbv {" ".join(gerber_filenames)} {edge_filename}'
    gerbv_command += f' {" ".join(foreground_array)}'
    gerbv_command += f" -o {not_cropped_name}"
    gerbv_command += f" --dpi={dpi} --export=png -a"
    subprocess.call(gerbv_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True)

    setup_imagic(not_cropped_name, output_filename)


def fb_gbr2png(gerber_filename: str, edge_filename: str, output_filename: str) -> None:
    """Generate PNG from gerber file.

    Generates PNG of a gerber using gerbv and convert.
    Edge cuts gerber is used to crop the image correctly.
    """
    dpi = 1000

    logger.debug("Generating PNG for %s", gerber_filename)
    not_cropped_name = f"{output_filename.split('.')[0]}_not_cropped.png"

    gerbv_command = f"gerbv {gerber_filename} {edge_filename}"
    gerbv_command += " --background=#000000 --foreground=#ffffffff --foreground=#00000f"
    gerbv_command += f" -o {not_cropped_name}"
    gerbv_command += f" --dpi={dpi} --export=png -a"
    subprocess.call(gerbv_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True)

    setup_imagic(not_cropped_name, output_filename)


def setup_imagic(not_cropped_name: str, output_filename: str) -> None:
    """Set imagic settings."""
    not_cropped_image = PIL.Image.open(not_cropped_name)
    cropped_image = not_cropped_image.crop(not_cropped_image.getbbox())
    img = PIL.ImageOps.invert(cropped_image)
    img.save(output_filename)

    imagic_command = f"convert {output_filename}"
    imagic_command += " -threshold 50% -transparent white -blur 1 +antialias"
    imagic_command += f" {output_filename}"
    subprocess.call(imagic_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True)

    os.remove(not_cropped_name)


def main():
    """Process gerbers to png."""
    process_gbrs_to_pngs()


if __name__ == "__main__":
    main()
