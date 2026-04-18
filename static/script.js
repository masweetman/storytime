// Handle story page - redirect to home if no story data
if (window.location.pathname === '/story') {
    document.addEventListener('DOMContentLoaded', () => {
        const storyData = JSON.parse(sessionStorage.getItem('storyData') || '{}');
        if (!storyData.story) {
            window.location.href = '/';
        }
    });
}
