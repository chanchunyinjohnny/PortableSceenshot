from setuptools import setup, find_packages

with open("requirements.txt") as f:
    requirements = f.read().splitlines()

setup(
    name="PortableScreenshot",
    version="0.1.0",
    description="Lightweight portable screenshot tool for Windows",
    author="Contributors",
    python_requires=">=3.9",
    install_requires=requirements,
    py_modules=["screenshot_tool"],
    entry_points={
        "console_scripts": [
            "portable-screenshot=screenshot_tool:main",
        ],
    },
)
