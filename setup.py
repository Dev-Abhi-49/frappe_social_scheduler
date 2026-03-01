from setuptools import setup, find_packages

# with open("requirements.txt") as f:
#     install_requires = f.read().strip().split("\n")

setup(
    name="frappe_social",
    version="1.0.0",
    description="Social media scheduling and analytics module for Frappe",
    author="Abhishek Hiremath",
    author_email="abhishek.dev.4949@gmail.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    # install_requires=install_requires,
    python_requires=">=3.10",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Framework :: Frappe",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Communications",
    ],
)
