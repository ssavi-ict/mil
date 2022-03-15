# Using the PyCharm IDE
This is a quick guide for how to set up your development environment if you'd like to use PyCharm

**Note, this guide assumes you have already cloned the repository as described in the** [Contributing Guide](contributing)

## Cloning the Repository
If you'd like to use PyCharm, you'll be setting up the mil repository in your PyCharmProjects folder for development.
### Step 1
Open PyCharm 


#reference markup below

It is important that these commands are all run from **the root of the repository**.

**Navigate to the root of the repository now.**

If you have followed the intructions from the [Contributing Guide](contributing) exactly, you can get there by running

`cd ~/catkin_ws/src/mil`



## System Requirements

### Operating System
**It is recommended that you [dual boot Ubuntu 18.04](https://help.ubuntu.com/community/WindowsDualBoot) for development**

We have made efforts to containerize out development environment to support other linux
distributions, OSX, and possibly Windows, but these platforms are not officially
supported.

Virtual Machines will be able to run our software, but it may be too slow (see [hardware](#hardware))

### Hardware
Autonomous robotics is computationally expensive, especially when running simulations.
If you can, use a powerful computer. We recommend you have at least 8GB RAM and a modern i5 or better CPU. Many tasks such as simulation and computer vision will run faster on a system with a GPU.


## Install Docker
It is recommended that you build and run MIL code within a Docker container.
This process will differ depending on your host operating system, but it
well documented for Windows, OSX, and several Linux operating systems.

* [Ubuntu](https://docs.docker.com/install/linux/docker-ce/ubuntu/)
* [Windows](https://docs.docker.com/docker-for-windows/install/)
* [OSX](https://docs.docker.com/docker-for-mac/install/)

*Note: if you use Docker Desktop (Windows or OSX), be sure to move the RAM/CPU sliders to max*

You also need to give your user access to the docker group
* Ubuntu: `sudo usermod -a -G docker $USER` then reboot

*NOTE: In the Docker contianer, no GUI applications will be availible. The terminal interface will be the only way to interact with the container. However, all ROS.Gazebo GUI utilities (RViz, GazeboClient, and RQT) will work when run on the host machine because the Development Docker Container is attached to the host network*

### Alternative: run the setup scripts on your host operating system
If you are running Ubuntu 18.04 and prefer to simply run code directly on your "host"
operating system without using Docker, you can run the following scripts from the root of the repository

`./scripts/system_install`

`./scripts/user_install`

*NOTE: now the MIL aliases will work on your machine. You can type* `mil` *to take you to the root of the repo anytime*


## Build the containers
Now that you have docker installed, you must build the development container which
you will build and test code in.

From the root of the cloned repository in your *host operating system*, run:

`./scripts/build_docker_containers`

This process requires internet and may take a while (up to an hour is common).

##  Getting setup in the development container

### Runing the development container
Now that the development container is built, you can run the container.

`./scripts/run_developement_container`

This will open a shell into a Ubuntu instance where you can build and test the
code in this repository (including your changes!).

*Note: if you are not user 1000 on the host machine, you will need to first run `./fix_ownership_for_docker` from the host machine*

Note that the clone of the repository from your host system is mounted into the container,
so changes to the code in your host system are also changed in the container and visa-versa.
This allows you to modify your code in your editor of choice on your host system while
building and testing changes within the container.

### Starting a tmux session in the development container
When using ROS and Gazebo, many terminals are required. [tmux](https://www.hamvocke.com/blog/a-quick-and-easy-guide-to-tmux/) is a program which allows one terminal to be split into many terminals each called a panel. We highly recommend its use when runnning code, esspecially when working in a docker container.

1. Start a tmux session from the container (allows you to have multiple terminals within the container) `tmux new`
1. Split the tmux session with `Control+B` then `"`. You can switch between the terminals with `Control+B` then up arrow / down arrow

## Build the repository
Now that you are inside the development container, try building the repository.

We have a convenient alias for this, run `cm`

If something goes wrong, try the suggestions in [Getting Help](help)

## (Optional) Install proprietary software
MIL uses a few proprietary packages which cannot be distributed with the repo.
You are able to compile the repo and run simulations without them, but
they must be installed on the actual robots.

* `./scripts/install_bvtsdk` - installs the BlueView Imaging Sonar SDK
* `./scripts/install_flycap`- installs the Pointgrey Flycapture SDK

These scripts will prompt you for an encryption password. Ask a MIL leader for this.

## (Optional) Install UDEV rules
If you plan on running certain MIL sensors from your local machine
or are setting up the install on a robot, you must give your user
access to certain USB devices through UDEV.

`./scripts/install_udev_rules`

## Run some code
Now that the repository is built, try running something!

For example, [SubjuGator](/docs/subjugator/index)
