#!/bin/sh

sed -i 's|<AuthenticationMethod>.*</AuthenticationMethod>|<AuthenticationMethod>External</AuthenticationMethod>|' $STORAGE_LOCATION/radarr/config/config.xml
sed -i 's|<AuthenticationMethod>.*</AuthenticationMethod>|<AuthenticationMethod>External</AuthenticationMethod>|' $STORAGE_LOCATION/sonarr/config/config.xml
