$(document).ready(function() {
    const burgerMenu = $('#burger-menu');
    const container = $('.container');
    const body = $('body');
    const bgUrl = body.data('bg-url');

    body.removeClass('light-mode').addClass('dark-mode');
    localStorage.removeItem('theme');

    if (bgUrl) {
        body.css('--workspace-bg-image', "url('" + bgUrl + "')").addClass('bg-active');
    } else {
        body.css('--workspace-bg-image', 'none').removeClass('bg-active');
    }

    burgerMenu.on('click', function() {
        container.toggleClass('show-sidebar');
    });

    // change all the times to user's local/client time
    $('[data-utc-time]').each(function() {
        const utcTime = $(this).data('utcTime');
        $(this).text(new Date(utcTime).toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false // Force 24-hour format
        }));
    });
    
    // Scroll chat to bottom when page loads
    const conversationContainer = document.getElementById('conversation-container');
    if (conversationContainer) {
        conversationContainer.scrollTop = conversationContainer.scrollHeight;
    }
});
