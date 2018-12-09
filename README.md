# docker-media-server
compose and other things for home configuration of dockerized media server.

## Installation:

- If this is the first start, create a new Docker user, for example porpuses we will call it dockeruser

`adduser dockeruser`

- Once user is create, we will need to get its UID, for example porpuses we will assume the id is 1000

`id -u dockeruser`

- Create two env variables on your system with:

`PUID=1000`
`GUID=1000`

- Create environmet varibles file (variables.env) or define DOMAIN_URL, PLEX_CLAIM, GUID and PUID environmet variables in your system. (https://docs.docker.com/compose/env-file/)

- Change directory to your docker-compose path and execute docker-compose up -d . Wait for initialization.

- One time PLEX configuration. You may need to login using ssh tunnel, to
access to plex webapp via localhost. You can use the following script:

`ssh -L port:localhost:port user@remote`

For Plex, this could be:

`ssh -L 32400:localhost:32400 root@yourserverip`

- Once connected, browse with any browser to localhost:32400/web and Plex should show up.

- Once Plex is fully configured, you can disconnect the SSH Tunnel.

- (Optional) Copy extra files, like PLEX Plugins and such in their respective directories. This has to be done once the first time init is finished.

`cp pluginpath $PLEX_HOME/Library/Application Support/Plex Media Server/Plug-ins`
