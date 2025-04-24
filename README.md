# dog-heater

## Set up
1. Edit `config.yaml` and enter MQTT host and credentials
2. Copy `heater.service` to `/lib/systemd/system/heater.service`
3. Run:  
```bash
    sudo pip3 install -r requirements.txt
    sudo systemctl daemon-reload
    sudo systemctl enable heater
    sudo systemctl start heater
    sudo systemctl is-enabled heater
    sudo systemctl is-active heater
    sudo service heater status
```