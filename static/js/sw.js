self.addEventListener('push', function(event) {
    let data = {};
    try {
        data = event.data.json();
    } catch (e) {
        data = { title: 'Rosette Wellness', body: 'You have a new notification.' };
    }

    const title = data.title || 'Rosette Wellness';
    const options = {
        body: data.body || '',
        icon: '/static/images/icon-192.png',
        badge: '/static/images/icon-192.png',
        data: { url: data.url || '/masseuse/' },
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    const url = event.notification.data.url || '/masseuse/';
    event.waitUntil(
        clients.matchAll({ type: 'window' }).then(function(clientList) {
            for (const client of clientList) {
                if (client.url.includes('/masseuse/') && 'focus' in client) {
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow(url);
            }
        })
    );
});
