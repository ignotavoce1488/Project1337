
    (function() {
      try {
        var override = localStorage.getItem('slovech_theme_override');
        var theme = 'dark';
        if (override === 'light' || override === 'dark') {
          theme = override;
        } else {
          // Detect Telegram client theme from URL hash or WebApp SDK
          var hash = window.location.hash || '';
          var match = hash.match(/tgWebAppThemeParams=([^&]+)/) || hash.match(/tgThemeParams=([^&]+)/);
          var detected = false;
          if (match && match[1]) {
            try {
              var p = JSON.parse(decodeURIComponent(match[1]));
              if (p.bg_color) {
                var hex = p.bg_color.replace('#', '');
                if (hex.length === 3) hex = hex.split('').map(function(c){return c+c;}).join('');
                var r = parseInt(hex.substring(0, 2), 16) || 0;
                var g = parseInt(hex.substring(2, 4), 16) || 0;
                var b = parseInt(hex.substring(4, 6), 16) || 0;
                if ((0.2126 * r + 0.7152 * g + 0.0722 * b) > 130) theme = 'light';
                detected = true;
              }
            } catch(e) {}
          }
          if (!detected && window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
            theme = 'light';
          }
        }
        document.documentElement.setAttribute('data-theme', theme);
        var accent = localStorage.getItem('slovech_accent') || 'lavender';
        document.documentElement.setAttribute('data-accent', accent);
      } catch (err) {}
    })();
