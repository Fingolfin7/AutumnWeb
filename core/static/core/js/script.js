$(document).ready(function() {
    const toggleSwitch = $('#theme-switch');
    const currentTheme = localStorage.getItem('theme') || 'light';
    const burgerMenu = $('#burger-menu');
    const container = $('.container');
    const body = $('body');

    body.addClass(currentTheme + '-mode');
    toggleSwitch.prop('checked', currentTheme === 'dark');

    toggleSwitch.on('change', function() {
        let theme = 'light';
        if ($(this).prop('checked')) {
            theme = 'dark';
        }
        
        // Remove both classes first
        body.removeClass('light-mode dark-mode');
        // Add the appropriate class
        body.addClass(theme + '-mode');
        
        localStorage.setItem('theme', theme);
    });

    burgerMenu.on('click', function() {
        container.toggleClass('show-sidebar');
    });

    // change all the times to user's local/client time
    $('[data-utc-time]').each(function() {
        const utcTime = $(this).data('utcTime');
        $(this).text(new Date(utcTime).toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        }));
    });
    
    // Scroll chat to bottom when page loads
    const conversationContainer = document.getElementById('conversation-container');
    if (conversationContainer) {
        conversationContainer.scrollTop = conversationContainer.scrollHeight;
    }
});
