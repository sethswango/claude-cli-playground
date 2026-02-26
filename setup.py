from setuptools import setup

# Read version from the module without importing it
version = {}
with open("sysglance.py") as f:
    for line in f:
        if line.startswith("__version__"):
            exec(line, version)
            break

setup(
    name='sysglance',
    version=version['__version__'],
    py_modules=['sysglance'],
    install_requires=['rich', 'psutil'],
)
