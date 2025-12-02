// Load navbar và set active tab
fetch('navbar.html')
    .then(response => response.text())
    .then(data => {
        document.getElementById('navbar-container').innerHTML = data;
        
        // Lấy tên file hiện tại
        const currentPage = window.location.pathname.split('/').pop();
        
        // Set active cho tab tương ứng
        const navMap = {
            'home.html': 'nav-home',
            'config.html': 'nav-config',
            'monitor.html': 'nav-monitor',
            'resolume.html': 'nav-resolume',
            'motion.html': 'nav-motion',
            'map.html': 'nav-map'
        };
        
        const activeNavId = navMap[currentPage];
        if (activeNavId) {
            document.getElementById(activeNavId).classList.add('active');
        }
    });
