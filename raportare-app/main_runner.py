from main import app, init_db

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5050, debug=False, use_reloader=False)
