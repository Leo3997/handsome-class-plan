/** @type {import('tailwindcss').Config} */
module.exports = {
    // 1. 告诉 Tailwind 你的 HTML 文件在哪里，它需要扫描这些文件来决定生成哪些 CSS
    content: [
        "./templates/**/*.html", // 扫描 templates 目录下所有 HTML
        "./static/**/*.js",      // 如果你的 JS 里也写了类名，也要扫描
        "./*.html"               // 扫描根目录下的 HTML (如果有的话)
    ],
    theme: {
        extend: {
            // 2. 这里是从你 index.html 里搬过来的字体配置
            fontFamily: {
                sans: ['"Nunito"', 'sans-serif'],
                display: ['"Quicksand"', 'sans-serif']
            },
            // 3. 这里是从你 index.html 里搬过来的颜色配置
            colors: {
                clay: {
                    bg: '#f0f4f8', // 注意：你 index.html 是 #f0f4f8，login.html 是 #eef2f6，建议统一
                    card: '#ffffff',
                    primary: '#63b3ed',
                    secondary: '#f6ad55',
                    accent: '#fc8181',
                    text: '#4a5568',
                    muted: '#a0aec0'
                }
            },
            // 4. 阴影配置
            boxShadow: {
                'clay-card': '8px 8px 16px #d1d9e6, -8px -8px 16px #ffffff',
                'clay-btn': '6px 6px 12px #b8b9be, -6px -6px 12px #ffffff',
                'clay-btn-active': 'inset 4px 4px 8px #b8b9be, inset -4px -4px 8px #ffffff',
                'clay-inner': 'inset 6px 6px 12px #d1d9e6, inset -6px -6px 12px #ffffff',
            },
            // 5. 圆角配置
            borderRadius: {
                'clay': '1.5rem',
            }
        },
    },
    plugins: [],
}
