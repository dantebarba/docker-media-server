# docker-media-server
compose and other 'yerbs' for home configuration of dockerized media server.

## Installation:

- Crear la estructura de archivos necesaria para docker en la carpeta ~/docker/ (TODO: Podría ser automatizado.)
- Iniciar utilizando docker-compose up -d el media-server.
- Configurar por primera vez el media server. Necesitamos entrar con
ssh tunnel al servidor, podemos usar:

`ssh -L port:localhost:port user@remote`

- Copiar los archivos extras, los plugins de plex en la carpeta plugins de Plex:

`cp pluginpath $PLEX_HOME/Library/Application Support/Plex Media Server/Plug-ins`
