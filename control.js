// Control functions for ESP32
function getSelectedDevice() {
    // Check if Config All mode is active (priority check)
    const configAllDevices = JSON.parse(localStorage.getItem('configAllDevices') || '[]');
    const configAllActive = localStorage.getItem('configAllActive') === 'true';
    
    if (configAllActive && configAllDevices.length > 0) {
        // Return array of all devices for Config All mode
        console.log('Config All mode active:', configAllDevices.length, 'devices');
        return configAllDevices.map(d => ({
            ip: d.ip,
            port: d.port
        }));
    }
    
    // Single device mode
    const ip = localStorage.getItem('selected_esp_ip');
    const port = localStorage.getItem('selected_esp_port');
    
    if (!ip || !port) {
        alert('⚠️ Chưa chọn thiết bị!\n\nVui lòng vào tab HOME và click "Access" trên thiết bị muốn điều khiển.');
        return null;
    }
    
    return { ip, port: parseInt(port) };
}

function sendCommand(command) {
    const device = getSelectedDevice();
    if (!device) return Promise.reject('No device selected');
    
    // Check if device is an array (Config All mode)
    if (Array.isArray(device)) {
        console.log(`Sending command to ${device.length} devices:`, command);
        
        // Send command to all devices
        const promises = device.map(d => 
            fetch('/api/send-command', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    ip: d.ip,
                    port: d.port,
                    command: command
                })
            })
            .then(response => response.json())
            .then(data => {
                console.log(`Command sent to ${d.ip}:${d.port}:`, data.success ? '✓' : '✗');
                return data.success;
            })
            .catch(error => {
                console.error(`Error sending to ${d.ip}:${d.port}:`, error);
                return false;
            })
        );
        
        // Wait for all commands to complete
        return Promise.all(promises).then(results => {
            const successCount = results.filter(r => r).length;
            console.log(`Config All: ${successCount}/${device.length} devices responded`);
            return successCount > 0;
        });
    }
    
    // Single device mode
    return fetch('/api/send-command', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            ip: device.ip,
            port: device.port,
            command: command
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            console.log('Command sent:', command);
            return true;
        } else {
            throw new Error('Command failed');
        }
    })
    .catch(error => {
        console.error('Error sending command:', error);
        return false;
    });
}

// LED Control Functions
function toggleLED(button) {
    const isEnabled = button.textContent.includes('Bật');
    const command = `LED:${isEnabled ? 0 : 1}`;
    
    sendCommand(command).then(success => {
        if (success) {
            if (isEnabled) {
                button.textContent = '🔴 LED: Tắt';
                button.className = 'btn btn-danger';
            } else {
                button.textContent = '🟢 LED: Bật';
                button.className = 'btn btn-success';
            }
        }
    });
}

function toggleConfigMode(button) {
    const isEnabled = button.textContent.includes('Tắt');
    const command = `CONFIG:${isEnabled ? 1 : 0}`;
    
    sendCommand(command).then(success => {
        if (success) {
            if (isEnabled) {
                button.textContent = '🟡 Config: Bật';
                button.className = 'btn btn-warning';
                document.getElementById('config-status').textContent = '🟡 Config Mode: ESP32 nhận lệnh LED';
                document.getElementById('config-status').style.color = '#f39c12';
            } else {
                button.textContent = '🔵 Config: Tắt';
                button.className = 'btn btn-primary';
                document.getElementById('config-status').textContent = '🔵 Config Mode: Tắt';
                document.getElementById('config-status').style.color = '#3498db';
            }
        }
    });
}

function chooseColor() {
    const colorInput = document.getElementById('color-picker');
    if (!colorInput) {
        // Create color input if not exists
        const input = document.createElement('input');
        input.type = 'color';
        input.id = 'color-picker';
        input.style.display = 'none';
        input.onchange = function() {
            const hex = this.value;
            const r = parseInt(hex.substr(1,2), 16);
            const g = parseInt(hex.substr(3,2), 16);
            const b = parseInt(hex.substr(5,2), 16);
            
            setLEDColor(r, g, b);
        };
        document.body.appendChild(input);
        input.click();
    } else {
        colorInput.click();
    }
}

function setLEDColor(r, g, b) {
    const brightness = parseInt(document.getElementById('brightness-slider').value);
    const adjR = Math.floor(r * brightness / 255);
    const adjG = Math.floor(g * brightness / 255);
    const adjB = Math.floor(b * brightness / 255);
    
    const command = `LEDCTRL:ALL,${adjR},${adjG},${adjB}`;
    
    sendCommand(command).then(success => {
        if (success) {
            document.getElementById('color-preview').style.backgroundColor = `rgb(${r}, ${g}, ${b})`;
            document.getElementById('rgb-info').textContent = `RGB: (${r}, ${g}, ${b}) | Độ sáng: ${brightness}`;
        }
    });
}

function setBrightness(value) {
    document.getElementById('brightness-value').textContent = value;
    // Would need to resend last color with new brightness
}

function setDirection(dir) {
    const command = `DIR:${dir}`;
    sendCommand(command).then(success => {
        if (success) {
            const dirText = dir === 1 ? 'Move Up' : 'Move Down';
            document.getElementById('direction-status').textContent = `✅ Chiều: ${dirText}`;
        }
    });
}

function sendRainbow() {
    const command = 'RAINBOW:START';
    sendCommand(command);
}

function testLED() {
    const command = 'LEDCTRL:ALL,255,255,255';
    sendCommand(command);
}

// Xilanh animation state
let pistonPosition = 0; // 0 = bottom, 100 = top
let pistonInterval = null;
let cycleTime = 5.0; // seconds for full cycle (0% to 100%)

// Calculate animation parameters based on cycle time
function getAnimationParams() {
    const ANIMATION_INTERVAL = 50; // ms between updates (fixed for smooth animation)
    const totalSteps = (cycleTime * 1000) / ANIMATION_INTERVAL; // number of updates in full cycle
    const PISTON_SPEED = 100 / totalSteps; // % per update to complete in cycleTime
    return { PISTON_SPEED, ANIMATION_INTERVAL };
}

// Set cycle time
function setCycleTime(value) {
    cycleTime = parseFloat(value);
    document.getElementById('cycle-time-value').textContent = cycleTime.toFixed(1);
}

// Xilanh Control Functions
function xilanhUp() {
    const command = 'XILANH:2';
    sendCommand(command).then(success => {
        if (success) {
            document.getElementById('xilanh-status').textContent = '🟢 XI LANH: MOVING UP';
            document.getElementById('xilanh-status').style.color = '#27ae60';
            animatePiston('up');
        }
    });
}

function xilanhDown() {
    const command = 'XILANH:1';
    sendCommand(command).then(success => {
        if (success) {
            document.getElementById('xilanh-status').textContent = '🔵 XI LANH: MOVING DOWN';
            document.getElementById('xilanh-status').style.color = '#3498db';
            animatePiston('down');
        }
    });
}

function xilanhStop() {
    const command = 'XILANH:0';
    sendCommand(command).then(success => {
        if (success) {
            document.getElementById('xilanh-status').textContent = '🔴 XI LANH: STOPPED';
            document.getElementById('xilanh-status').style.color = '#e74c3c';
            stopPiston();
        }
    });
}

// Animate piston movement
function animatePiston(direction) {
    stopPiston(); // Clear any existing animation
    
    const cylinderHeight = 200; // Height of cylinder container
    const pistonHeight = 60;    // Height of piston
    const maxTravel = cylinderHeight - pistonHeight; // 140px max travel distance
    
    const { PISTON_SPEED, ANIMATION_INTERVAL } = getAnimationParams();
    
    pistonInterval = setInterval(() => {
        const piston = document.getElementById('piston');
        const positionText = document.getElementById('piston-position');
        
        if (!piston || !positionText) return;       
        
        if (direction === 'up') {
            pistonPosition = Math.min(100, pistonPosition + PISTON_SPEED);
        } else if (direction === 'down') {
            pistonPosition = Math.max(0, pistonPosition - PISTON_SPEED);
        }
        
        // Calculate bottom position in pixels: 0% = 0px (bottom), 100% = 140px (top)
        const bottomPosition = (pistonPosition / 100) * maxTravel;
        piston.style.bottom = `${bottomPosition}px`;
        positionText.textContent = `Vị trí: ${Math.round(pistonPosition)}%`;
        
        // Stop at limits and send STOP command
        if (pistonPosition >= 100 || pistonPosition <= 0) {
            stopPiston();
            // Send STOP command when reaching 0% or 100%
            sendCommand('XILANH:0').then(success => {
                if (success) {
                    console.log(`Xi lanh reached ${Math.round(pistonPosition)}%, sent STOP command`);
                    // Update status display
                    const statusElement = document.getElementById('xilanh-status');
                    if (statusElement) {
                        statusElement.textContent = '🟢 XI LANH: STOPPED (Auto)';
                        statusElement.style.color = '#27ae60';
                    }
                }
            });
        }
    }, ANIMATION_INTERVAL);
}

function stopPiston() {
    if (pistonInterval) {
        clearInterval(pistonInterval);
        pistonInterval = null;
    }
}

// Touch Control Functions
function sendThreshold() {
    const threshold = document.getElementById('threshold-input').value;
    const command = `THR:${threshold}`;
    
    sendCommand(command).then(success => {
        if (success) {
            document.getElementById('threshold-status').textContent = `✅ Đã gửi ngưỡng: ${threshold}`;
            document.getElementById('threshold-status').style.color = '#27ae60';
        } else {
            document.getElementById('threshold-status').textContent = '❌ Lỗi gửi ngưỡng';
            document.getElementById('threshold-status').style.color = '#e74c3c';
        }
    });
}

function sendCustomCommand() {
    const command = document.getElementById('custom-command').value;
    if (!command.trim()) {
        alert('Vui lòng nhập command!');
        return;
    }
    
    sendCommand(command).then(success => {
        if (success) {
            document.getElementById('command-status').textContent = `✅ Đã gửi: ${command}`;
            document.getElementById('command-status').style.color = '#27ae60';
        } else {
            document.getElementById('command-status').textContent = '❌ Lỗi gửi command';
            document.getElementById('command-status').style.color = '#e74c3c';
        }
    });
}

// Display selected device info
function updateDeviceInfo() {
    const device = getSelectedDevice();
    const infoElements = document.querySelectorAll('.device-info-display');
    
    infoElements.forEach(el => {
        if (device) {
            el.textContent = `🎯 Đang điều khiển: ${device.ip}:${device.port}`;
            el.style.color = '#27ae60';
        } else {
            el.textContent = '⚠️ Chưa chọn thiết bị';
            el.style.color = '#e74c3c';
        }
    });
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', updateDeviceInfo);
