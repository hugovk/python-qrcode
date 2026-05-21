#!/usr/bin/env python
"""
qr - Convert stdin (or the first argument) to a QR Code.

When stdout is a tty the QR Code is printed to the terminal and when stdout is
a pipe to a file an image is written. The default image format is PNG.
"""

from __future__ import annotations

import optparse
import os
import sys
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import qrcode

if TYPE_CHECKING:
    from collections.abc import Iterable

    from qrcode.image.base import BaseImage, DrawerAliases

# The next block is added to get the terminal to display properly on MS platforms
if sys.platform.startswith(("win", "cygwin")):  # pragma: no cover
    import colorama

    colorama.init()

default_factories = {
    "pil": "qrcode.image.pil.PilImage",
    "png": "qrcode.image.pure.PyPNGImage",
    "svg": "qrcode.image.svg.SvgImage",
    "svg-fragment": "qrcode.image.svg.SvgFragmentImage",
    "svg-path": "qrcode.image.svg.SvgPathImage",
    "styled-pil": "qrcode.image.styledpil.StyledPilImage",
    # Keeping for backwards compatibility:
    "pymaging": "qrcode.image.pure.PymagingImage",
}

error_correction = {
    "L": qrcode.ERROR_CORRECT_L,
    "M": qrcode.ERROR_CORRECT_M,
    "Q": qrcode.ERROR_CORRECT_Q,
    "H": qrcode.ERROR_CORRECT_H,
}


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    version = metadata.version("qrcode")
    parser = optparse.OptionParser(usage=(__doc__ or "").strip(), version=version)

    # Wrap parser.error in a typed NoReturn method for better typing.
    def raise_error(msg: str) -> NoReturn:
        parser.error(msg)
        raise  # pragma: no cover # noqa: PLE0704

    parser.add_option(
        "--factory",
        help="Full python path to the image factory class to "
        "create the image with. You can use the following shortcuts to the "
        f"built-in image factory classes: {commas(default_factories)}.",
    )
    parser.add_option(
        "--factory-drawer",
        help=f"Use an alternate drawer. {get_drawer_help()}.",
    )
    parser.add_option(
        "--optimize",
        type=int,
        help="Optimize the data by looking for chunks "
        "of at least this many characters that could use a more efficient "
        "encoding method. Use 0 to turn off chunk optimization.",
    )
    parser.add_option(
        "--error-correction",
        type="choice",
        choices=sorted(error_correction.keys()),
        default=None,
        help="The error correction level to use. Choices are L (7%), "
        "M (15%, default), Q (25%), and H (30%). When --embedded-image-path "
        "is used, H is required and used by default.",
    )
    parser.add_option(
        "--ascii", help="Print as ascii even if stdout is piped.", action="store_true"
    )
    parser.add_option(
        "--output",
        help="The output file. If not specified, the image is sent to "
        "the standard output.",
    )
    parser.add_option(
        "--embedded-image-path",
        help="Path to an image to embed in the center of the QR code. "
        "Implies --factory styled-pil and --error-correction H.",
    )
    parser.add_option(
        "--embedded-image-ratio",
        type=float,
        help="Size of the embedded image as a ratio of the QR code width, "
        "between 0 and 1 (default 0.25). Requires --embedded-image-path.",
    )

    opts, args = parser.parse_args(args)

    if opts.embedded_image_ratio is not None and not opts.embedded_image_path:
        raise_error("--embedded-image-ratio requires --embedded-image-path.")

    if opts.embedded_image_path:
        if opts.error_correction is not None and opts.error_correction != "H":
            raise_error(
                "--embedded-image-path requires --error-correction H."
            )
        opts.error_correction = "H"
        if opts.factory is None:
            opts.factory = "styled-pil"
    elif opts.error_correction is None:
        opts.error_correction = "M"

    if opts.factory:
        module = default_factories.get(opts.factory, opts.factory)
        try:
            image_factory = get_factory(module)
        except ValueError as e:
            raise_error(str(e))
    else:
        image_factory = None

    qr = qrcode.QRCode(
        error_correction=error_correction[opts.error_correction],
        image_factory=image_factory,
    )

    if args:
        data = args[0]
        data = data.encode(errors="surrogateescape")
    else:
        data = sys.stdin.buffer.read()
    if opts.optimize is None:
        qr.add_data(data)
    else:
        qr.add_data(data, optimize=opts.optimize)

    image_kwargs = {}
    if opts.embedded_image_path:
        image_kwargs["embedded_image_path"] = opts.embedded_image_path
    if opts.embedded_image_ratio is not None:
        image_kwargs["embedded_image_ratio"] = opts.embedded_image_ratio

    if opts.output:
        img = qr.make_image(**image_kwargs)
        with Path(opts.output).open("wb") as out:
            img.save(out)
    else:
        if image_factory is None and (os.isatty(sys.stdout.fileno()) or opts.ascii):
            qr.print_ascii(tty=not opts.ascii)
            return

        kwargs = {}
        aliases: DrawerAliases | None = getattr(
            qr.image_factory, "drawer_aliases", None
        )
        if opts.factory_drawer:
            if not aliases:
                raise_error("The selected factory has no drawer aliases.")
            if opts.factory_drawer not in aliases:
                raise_error(
                    f"{opts.factory_drawer} factory drawer not found."
                    f" Expected {commas(aliases)}"
                )
            drawer_cls, drawer_kwargs = aliases[opts.factory_drawer]
            kwargs["module_drawer"] = drawer_cls(**drawer_kwargs)
        img = qr.make_image(**kwargs, **image_kwargs)

        sys.stdout.flush()
        img.save(sys.stdout.buffer)


def get_factory(module: str) -> type[BaseImage]:
    if "." not in module:
        raise ValueError("The image factory is not a full python path")
    module, name = module.rsplit(".", 1)
    imp = __import__(module, {}, {}, [name])
    return getattr(imp, name)


def get_drawer_help() -> str:
    help: dict[str, set] = {}

    for alias, module in default_factories.items():
        try:
            image = get_factory(module)
        except ImportError:  # pragma: no cover
            continue
        aliases: DrawerAliases | None = getattr(image, "drawer_aliases", None)
        if not aliases:
            continue
        factories = help.setdefault(commas(aliases), set())
        factories.add(alias)

    return ". ".join(
        f"For {commas(factories, 'and')}, use: {aliases}"
        for aliases, factories in help.items()
    )


def commas(items: Iterable[str], joiner="or") -> str:
    items = tuple(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} {joiner} {items[-1]}"


if __name__ == "__main__":  # pragma: no cover
    main()
