document.addEventListener('DOMContentLoaded', (event) => {
    const toggleSwitch = document.querySelector('#theme-switch');
    const currentTheme = localStorage.getItem('theme') || 'light';
    const burgerMenu = document.getElementById('burger-menu');
    const container = document.querySelector('.container');

    document.body.classList.add(currentTheme + '-mode');

    toggleSwitch.addEventListener('change', function() {
        let theme = 'light';
        if (this.checked) {
            theme = 'dark';
        }
        document.body.classList.toggle('light-mode', theme === 'light');
        document.body.classList.toggle('dark-mode', theme === 'dark');
        localStorage.setItem('theme', theme);
    });

    burgerMenu.addEventListener('click', () => {
        container.classList.toggle('show-sidebar');

    });
});
