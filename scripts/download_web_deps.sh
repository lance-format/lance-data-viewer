#!/bin/bash

# Configuration
VENDOR_DIR="web/vanilla/vendor"
mkdir -p "$VENDOR_DIR"

echo "Downloading web dependencies to $VENDOR_DIR..."

curl -L -o "$VENDOR_DIR/datatables.min.css" "https://cdn.datatables.net/v/dt/jq-3.7.0/dt-2.3.7/cr-2.1.2/date-1.6.3/sb-1.8.4/datatables.min.css"
curl -L -o "$VENDOR_DIR/datatables.min.js" "https://cdn.datatables.net/v/dt/jq-3.7.0/dt-2.3.7/cr-2.1.2/date-1.6.3/sb-1.8.4/datatables.min.js"

# Select2
curl -L -o "$VENDOR_DIR/select2.min.css" "https://cdn.jsdelivr.net/npm/select2@4.1.0-rc.0/dist/css/select2.min.css"
curl -L -o "$VENDOR_DIR/select2.min.js" "https://cdn.jsdelivr.net/npm/select2@4.1.0-rc.0/dist/js/select2.min.js"




echo "Done."
