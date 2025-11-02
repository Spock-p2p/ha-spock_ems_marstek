Home Assistant - Spock EMS (Marstek) Integration

Descargo de responsabilidad

Este es un módulo personalizado para Home Assistant. No está afiliado ni respaldado por Marstek o Spock.

Descripción

Esta integración conecta Home Assistant con el sistema Spock EMS, diseñado para funcionar con inversores Marstek.

Realiza dos acciones principales cada 30 segundos:

Envía telemetría (hardcoded por ahora) a la API de Spock (/api/fetcher_marstek).

Recibe comandos de la API de Spock (/api/ems_marstek) y (en el futuro) los ejecutará en el inversor local a través de Modbus UDP.

Instalación

HACS (Recomendado)

Ve a HACS > Integraciones > (Menú de 3 puntos) > "Repositorios personalizados".

Añade la URL de este repositorio (https://github.com/Spock-p2p/ha-hacs-ems-marstek) en la categoría "Integración".

Busca "Spock EMS (Marstek)" en HACS, instálalo y reinicia Home Assistant.

Instalación Manual

Copia el directorio custom_components/spock_ems_marstek de este repositorio a tu directorio <config>/custom_components/.

Reinicia Home Assistant.

Configuración

Después de la instalación, ve a Ajustes > Dispositivos y Servicios > Añadir Integración y busca "Spock EMS (Marstek)".

Se te pedirá la siguiente información:

Token API de Spock EMS: Tu token de autenticación (X-Auth-Token).

ID de Planta (Plant ID) de Spock EMS: El ID numérico de tu instalación.

Dirección IP del inversor Marstek: La IP local de tu inversor.

Puerto Modbus UDP del inversor Marstek: El puerto para la conexión Modbus UDP (por defecto: 30000).

Puedes cambiar estos valores más tarde haciendo clic en "Configurar" en la tarjeta de la integración.