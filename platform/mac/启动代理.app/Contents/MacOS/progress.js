// [INPUT]: UTF-8 阶段/文本状态文件，或 --result 直接结果。
// [OUTPUT]: 紧凑原生窗口，进度与结果复用；长错误可滚动，成功自动关闭。
// [POS]: Mac 共用提示视图；启动和停止共用，窗口不依赖 Python。
// [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
ObjC.import('Cocoa');

function parseStatus(text) {
    var separator = text.indexOf('\n');
    if (separator < 0) return null;
    var phase = text.slice(0, separator);
    if (['progress', 'success', 'error'].indexOf(phase) < 0) return null;
    return {phase: phase, message: text.slice(separator + 1)};
}

function run(argv) {
    var directResult = argv[0] === '--result';
    var statusFile = directResult ? null : argv[0];
    var activateFile = directResult ? null : argv[1];
    var application = $.NSApplication.sharedApplication;
    application.setActivationPolicy($.NSApplicationActivationPolicyAccessory);
    var window = $.NSWindow.alloc.initWithContentRectStyleMaskBackingDefer(
        $.NSMakeRect(0, 0, 360, 144), $.NSWindowStyleMaskTitled, $.NSBackingStoreBuffered, false);
    window.title = '清洗代理';
    window.center;
    var scroll = $.NSScrollView.alloc.initWithFrame($.NSMakeRect(18, 54, 324, 72));
    scroll.drawsBackground = false;
    scroll.hasVerticalScroller = true;
    scroll.autohidesScrollers = true;
    var label = $.NSTextView.alloc.initWithFrame($.NSMakeRect(0, 0, 324, 72));
    label.editable = false;
    label.selectable = true;
    label.drawsBackground = false;
    label.richText = false;
    label.font = $.NSFont.systemFontOfSize(14);
    label.textColor = $.NSColor.labelColor;
    label.textContainerInset = $.NSMakeSize(0, 2);
    label.verticallyResizable = true;
    label.horizontallyResizable = false;
    label.autoresizingMask = $.NSViewWidthSizable;
    label.textContainer.widthTracksTextView = true;
    label.textContainer.lineFragmentPadding = 0;
    scroll.documentView = label;
    window.contentView.addSubview(scroll);
    var spinner = $.NSProgressIndicator.alloc.initWithFrame($.NSMakeRect(18, 22, 324, 10));
    spinner.indeterminate = true;
    spinner.startAnimation(null);
    window.contentView.addSubview(spinner);
    var closeButton = $.NSButton.alloc.initWithFrame($.NSMakeRect(270, 12, 72, 28));
    closeButton.title = '关闭';
    closeButton.bezelStyle = $.NSBezelStyleRounded;
    closeButton.controlSize = $.NSControlSizeSmall;
    closeButton.font = $.NSFont.systemFontOfSize(13);
    closeButton.keyEquivalent = '\r';
    closeButton.hidden = true;
    window.contentView.addSubview(closeButton);
    var previousState = '';
    var closeAfter = null;

    function update(state) {
        if (!state) return;
        var token = state.phase + '\n' + state.message;
        if (token === previousState) return;
        previousState = token;
        label.string = state.message;
        var finalState = state.phase !== 'progress';
        spinner.hidden = finalState;
        closeButton.hidden = !finalState;
        if (finalState) spinner.stopAnimation(null);
        else spinner.startAnimation(null);
        closeAfter = state.phase === 'success' ? Date.now() + 2000 : null;
    }

    ObjC.registerSubclass({
        name: 'RelayStatusDelegate',
        methods: {
            'close:': {types: ['void', ['id']], implementation: function () { application.terminate(null); }},
            'tick:': {
                types: ['void', ['id']],
                implementation: function () {
                    if (statusFile) {
                        if (!$.NSFileManager.defaultManager.fileExistsAtPath(statusFile)) {
                            application.terminate(null);
                            return;
                        }
                        var text = $.NSString.stringWithContentsOfFileEncodingError(statusFile, $.NSUTF8StringEncoding, null);
                        if (text) update(parseStatus(ObjC.unwrap(text) || ''));
                    }
                    if (activateFile && $.NSFileManager.defaultManager.fileExistsAtPath(activateFile)) {
                        $.NSFileManager.defaultManager.removeItemAtPathError(activateFile, null);
                        window.makeKeyAndOrderFront(null);
                        application.activateIgnoringOtherApps(true);
                    }
                    if (closeAfter !== null && Date.now() >= closeAfter) application.terminate(null);
                }
            }
        }
    });
    var delegate = $.RelayStatusDelegate.alloc.init;
    closeButton.target = delegate;
    closeButton.action = 'close:';
    if (directResult) update({phase: argv[1], message: argv[2]});
    else update({phase: 'progress', message: '正在准备启动…'});
    $.NSTimer.scheduledTimerWithTimeIntervalTargetSelectorUserInfoRepeats(.15, delegate, 'tick:', null, true);
    window.makeKeyAndOrderFront(null);
    application.activateIgnoringOtherApps(true);
    application.run;
}
