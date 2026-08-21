#!/bin/bash
# Ver comentario del Dockerfile: este parche debe aplicarse en tiempo
# de ejecucion (aqui), no en tiempo de build -- /sys durante el build
# es el sistema de archivos real del host, de solo lectura. En el
# sandbox real de Lambda (o en el emulador local), estos paths no
# existen todavia, asi que la escritura si funciona ahi.
mkdir -p /sys/devices/system/cpu 2>/dev/null || true
echo "0-3" > /sys/devices/system/cpu/possible 2>/dev/null || true
echo "0-3" > /sys/devices/system/cpu/present 2>/dev/null || true

exec /lambda-entrypoint.sh "$@"
