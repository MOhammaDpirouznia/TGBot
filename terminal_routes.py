
# --- SSH Terminal Routes ---
from terminal_manager import TerminalManager

@app.route('/admin/terminal')
@admin_required
def admin_terminal():
    is_auth = session.get('terminal_auth', False)
    has_pin = db.get_setting('terminal_pin')
    return render_template('admin_terminal.html', is_auth=is_auth, has_pin=bool(has_pin))

@app.route('/admin/api/terminal/auth', methods=['POST'])
@admin_required
def admin_terminal_auth():
    action = request.form.get('action')
    if action == 'set_pin':
        new_pin = request.form.get('new_pin')
        if new_pin and len(new_pin) >= 4:
            db.set_setting('terminal_pin', new_pin)
            session['terminal_auth'] = True
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'پین باید حداقل ۴ کاراکتر باشد.'})
    
    elif action == 'login':
        pin = request.form.get('pin')
        saved_pin = db.get_setting('terminal_pin')
        if saved_pin and pin == saved_pin:
            session['terminal_auth'] = True
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'پین وارد شده اشتباه است.'})
    
    elif action == 'logout':
        session.pop('terminal_auth', None)
        return jsonify({'success': True})
        
    return jsonify({'success': False, 'error': 'عملیات نامعتبر'})

@app.route('/admin/api/terminal/run', methods=['POST'])
@admin_required
def admin_terminal_run():
    if not session.get('terminal_auth'):
        return jsonify({'success': False, 'error': 'لطفا ابتدا با پین لاگین کنید.'})
        
    cmd = request.form.get('command', '').strip()
    if not cmd:
        return jsonify({'success': False, 'error': 'دستور خالی است.'})
        
    mode = request.form.get('mode', 'local')
    
    if mode == 'local':
        success, output = TerminalManager.run_local_command(cmd)
        return jsonify({'success': success, 'output': output})
    elif mode == 'remote':
        host = request.form.get('host')
        port = int(request.form.get('port', 22))
        user = request.form.get('user')
        password = request.form.get('password')
        
        if not all([host, user, password]):
            return jsonify({'success': False, 'error': 'اطلاعات ورود ریموت ناقص است.'})
            
        success, output = TerminalManager.run_remote_command(host, port, user, password, cmd)
        return jsonify({'success': success, 'output': output})
        
    return jsonify({'success': False, 'error': 'حالت نامعتبر'})
