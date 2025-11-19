# Spock EMS (Marstek) - Integración para Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)

Esta es una integración personalizada para [Home Assistant (HA)](https://www.home-assistant.io/) que permite monitorizar y recibir datos de un sistema de gestión de energía (EMS) Spock, específicamente para hardware compatible con Marstek.

**Válida para baterias Marstek Venus-3 (en breve estará certificada para Marstek Venus-2)**

La integración se conecta a los endpoints en la nube de Spock para obtener telemetría en tiempo real de tu instalación (planta).

** Para utilizar esta integración es imprescindible crear un cuenta en Spock: https://spock.es/register **

## Características

* Obtiene datos de telemetría de la API en la nube de Spock.
* Crea entidades en Home Assistant para los siguientes sensores:
    * Potencia Fotovoltaica (PV)
    * Potencia de la Batería (carga/descarga)
    * Estado de Carga de la Batería (SOC)
    * Potencia de la Red (importación/exportación)
    * ... (y otros sensores relevantes)
* Se configura fácilmente a través del `configuration.yaml`.

---

## Instalación

### Método 1: HACS (Recomendado)

1.  Asegúrate de tener [HACS](https://hacs.xyz/) instalado en tu Home Assistant.
2.  Ve a la sección de HACS en tu panel de Home Assistant.
3.  Haz clic en "Integraciones".
4.  Haz clic en el menú de tres puntos en la esquina superior derecha y selecciona "Repositorios personalizados".
5.  En el campo "Repositorio", pega la URL de este repositorio: `https://github.com/Spock-p2p/ha-spock_ems_marstek/`
6.  En la categoría, selecciona "Integración".
7.  Haz clic en "Añadir".
8.  Ahora deberías ver "Spock EMS (Marstek)" en tu lista de integraciones. Haz clic en "Instalar".
9.  Reinicia Home Assistant.

### Método 2: Instalación Manual

1.  Descarga la última versión ([release](https://github.com/Spock-p2p/ha-spock_ems_marstek/releases)) de este repositorio.
2.  Descomprime el archivo.
3.  Copia la carpeta `spock_ems_marstek` (que se encuentra dentro de la carpeta `custom_components` del archivo ZIP) en el directorio `custom_components` de tu instalación de Home Assistant.
    * La ruta final debería ser: `<config_dir>/custom_components/spock_ems_marstek/`
4.  Reinicia Home Assistant.

---

## Configuración

Una vez instalada la integración, debes añadir la siguiente configuración a tu archivo `configuration.yaml`:

sensor:
  - platform: spock_ems_marstek
    plant_id: "TU_PLANT_ID"
    auth_token: "TU_X_AUTH_TOKEN_SECRETO"
    scan_interval: 60 # Opcional: intervalo en segundos (default: 60)

## Parámetros de Configuración

1.   Platform (Requerido): Debe ser spock_ems_marstek.
2.   Plant_id (Requerido): El identificador único (plant_id) de tu instalación.
3.   Auth_token (Requerido): El token de autenticación (X-Auth-Token) necesario para acceder a la API.

## Entidades Creadas

Una vez configurada y reiniciada, la integración creará automáticamente las siguientes entidades (con el prefijo sensor.spock_ems_):

1.   sensor.spock_ems_battery_soc: Estado de Carga de la Batería (%)
2.   sensor.spock_ems_battery_power: Potencia de la Batería (W) - Positivo (cargando), Negativo (descargando)
3.   sensor.spock_ems_pv_power: Potencia Fotovoltaica (W)
4.   sensor.spock_ems_grid_power: Potencia de la Red (W) - Positivo (importando), Negativo (exportando)
5.   sensor.spock_ems_battery_charge_allowed: Estado de Carga de Batería (On/Off)
6.   sensor.spock_ems_battery_discharge_allowed: Estado de Descarga de Batería (On/Off)

(Nota: Los nombres de las entidades pueden variar ligeramente. Revisa tu panel de "Entidades" en Home Assistant después de la instalación).

### Contribuciones

Las contribuciones son bienvenidas. Por favor, abre un "issue" para reportar bugs o un "pull request" para proponer mejoras.
