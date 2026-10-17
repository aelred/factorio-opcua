"""Point FreeOpcUa opcua-client 0.8.4 at a client certificate without its settings dialog.

Only for 0.8.4: opcua-client 1.0.2+ (Python 3.14) creates its own certificate.

opcua-client 0.8.4 crashes when its Settings -> Client Application Certificate
dialog closes (NameError: name 'QDialog' is not defined), before it saves the
choice. This stores the same two settings the dialog would.

Run it with the Python that has opcua-client installed, while opcua-client is closed:
    python3 scripts/opcua-client-set-cert.py ~/uaclient-cert
The folder is the one given to `factorio-opc make-client-cert`.
"""

import sys
from pathlib import Path

from PyQt5.QtCore import QCoreApplication, QSettings

folder = Path(sys.argv[1] if len(sys.argv) > 1 else "~/uaclient-cert").expanduser().resolve()
cert, key = folder / "client_cert.der", folder / "client_key.pem"
for f in (cert, key):
    if not f.is_file():
        sys.exit(f"missing {f}: run 'factorio-opc make-client-cert {folder}' first")

# Same names opcua-client uses (uaclient/mainwindow.py), so it reads these settings.
QCoreApplication.setOrganizationName("FreeOpcUa")
QCoreApplication.setApplicationName("OpcUaClient")
settings = QSettings()
settings.setValue("application_certificate_settings",
                  {"application_certificate": str(cert), "application_private_key": str(key)})
settings.sync()
print(f"opcua-client will use {cert} and {key}")
