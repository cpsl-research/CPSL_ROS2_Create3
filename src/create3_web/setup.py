from glob import glob
import os

from setuptools import find_packages, setup

package_name = 'create3_web'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        (os.path.join('share', package_name), ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        # Static frontend assets, located at runtime via the package share dir.
        (os.path.join('share', package_name, 'web'), glob('web/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='David Hunt',
    maintainer_email='dmh89@duke.edu',
    description='Lightweight web GUI for operating a CPSL iRobot Create 3.',
    license='MIT',
    entry_points={
        'console_scripts': [
            'create3_web = create3_web.main:main',
        ],
    },
)
