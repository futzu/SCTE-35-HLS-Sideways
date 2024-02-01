#!/usr/bin/env python3

import setuptools
import sideways

with open("README.md", "r") as fh:
    readme = fh.read()

setuptools.setup(
    name="sideways",
    version=sideways.version(),
    author="Adrian of Doom",
    author_email="spam@iodisco.com",
    description="SCTE-35 Injection for Adaptive BitRate HLS ",
    long_description=readme,
    long_description_content_type="text/markdown",
    url="https://github.com/futzu/sideways",
    packages=setuptools.find_packages(),
    scripts=['bin/sideways'],
    install_requires=[
        "iframes >= 0.0.7",
        "m3ufu >= 0.0.87",
        "umzz >= 0.0.31",
        "threefive >= 2.4.25",
        "new_reader >= 0.1.7",
        "x9k3 >= 0.2.57",
    ],
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Programming Language :: Python :: Implementation :: CPython",
    ],
    python_requires=">=3.6",
)
