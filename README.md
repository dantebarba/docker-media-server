# docker-media-server
compose and other 'yerbs' for home configuration of dockerized media server.

## Installation:
- Create environmet varibles file (variables.env) or define DOMAIN_URL and PLEX_CLAIM environmet variables in your system. (https://docs.docker.com/compose/env-file/)
- Change directory to your docker-compose path and execute docker-compose up -d . Wait for initialization.
- One time PLEX configuration. You may need to login using ssh tunnel, to
access to plex webapp via localhost. You can use the following script:

`ssh -L port:localhost:port user@remote`

- (Optional) Copy extra files, like PLEX Plugins and such in their respective directories. This has to be done once the first time init is finished.

`cp pluginpath $PLEX_HOME/Library/Application Support/Plex Media Server/Plug-ins`
