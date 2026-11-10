// vst3host.cpp - a tiny VST3 effect host with a C API, loaded by fx.py through ctypes.
// It lets the sampler OS run third-party VST3 effects without the pedalboard package.
// Build:  ./build.sh   (needs the Steinberg VST3 SDK: base, pluginterfaces, public.sdk - see build.sh)
// Licence note: the VST3 SDK is dual-licensed (GPLv3 / Steinberg VST3 licence); this file is yours to use.
#include "public.sdk/source/vst/hosting/module.h"
#include "public.sdk/source/vst/hosting/plugprovider.h"
#include "public.sdk/source/vst/hosting/hostclasses.h"
#include "public.sdk/source/vst/hosting/processdata.h"
#include "public.sdk/source/vst/hosting/parameterchanges.h"
#include "public.sdk/source/vst/hosting/eventlist.h"
#include "pluginterfaces/vst/ivstevents.h"
#include "public.sdk/source/vst/utility/stringconvert.h"
#include "pluginterfaces/vst/ivstaudioprocessor.h"
#include "pluginterfaces/vst/ivsteditcontroller.h"
#include "pluginterfaces/vst/ivstmidicontrollers.h"
#include "pluginterfaces/vst/ivstcomponent.h"
#include "pluginterfaces/gui/iplugview.h"
#include "pluginterfaces/gui/iplugviewcontentscalesupport.h"
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <poll.h>
#include <cstdlib>
#include <chrono>
#include <cstring>
#include <atomic>
#include <mutex>
#include <string>
#include <vector>

using namespace Steinberg;
using namespace Steinberg::Vst;

static HostApplication* g_host = nullptr;

// ---------------------------------------------------------------------------------------------
// Plug-in editor (the maker's own interface): an X11 window, an IPlugFrame and the Linux run loop
// the plug-in needs for its timers and its X11 events.  vh_editor_idle() must be called often.
// ---------------------------------------------------------------------------------------------
struct Editor : public IPlugFrame, public Linux::IRunLoop {
    std::atomic<int32> refs{1};
    Display* dpy = nullptr;
    Window win = 0;
    IPtr<IPlugView> view;
    struct FdH { IPtr<Linux::IEventHandler> h; int fd; };
    struct TmH { IPtr<Linux::ITimerHandler> h; uint64 ms; std::chrono::steady_clock::time_point next; };
    std::vector<FdH> fds;
    std::vector<TmH> timers;
    int width = 0, height = 0;
    long fdCalls = 0, timerCalls = 0;

    tresult PLUGIN_API queryInterface(const TUID _iid, void** obj) override {
        if (FUnknownPrivate::iidEqual(_iid, IPlugFrame::iid) || FUnknownPrivate::iidEqual(_iid, FUnknown::iid)) {
            addRef(); *obj = static_cast<IPlugFrame*>(this); return kResultOk; }
        if (FUnknownPrivate::iidEqual(_iid, Linux::IRunLoop::iid)) { addRef(); *obj = static_cast<Linux::IRunLoop*>(this); return kResultOk; }
        *obj = nullptr; return kNoInterface;
    }
    uint32 PLUGIN_API addRef() override { return ++refs; }
    uint32 PLUGIN_API release() override { return --refs; }      // owned by Host, never deleted through release()

    tresult PLUGIN_API resizeView(IPlugView* v, ViewRect* r) override {
        if (!r || !dpy) return kInvalidArgument;
        width = r->getWidth(); height = r->getHeight();
        XResizeWindow(dpy, win, width, height); XFlush(dpy);
        if (v) v->onSize(r);
        return kResultOk;
    }
    tresult PLUGIN_API registerEventHandler(Linux::IEventHandler* h, Linux::FileDescriptor fd) override { fds.push_back({h, fd}); return kResultOk; }
    tresult PLUGIN_API unregisterEventHandler(Linux::IEventHandler* h) override {
        for (size_t i = 0; i < fds.size();) { if (fds[i].h.get() == h) fds.erase(fds.begin() + i); else ++i; } return kResultOk; }
    tresult PLUGIN_API registerTimer(Linux::ITimerHandler* h, Linux::TimerInterval ms) override {
        timers.push_back({h, ms ? ms : 1, std::chrono::steady_clock::now() + std::chrono::milliseconds(ms)}); return kResultOk; }
    tresult PLUGIN_API unregisterTimer(Linux::ITimerHandler* h) override {
        for (size_t i = 0; i < timers.size();) { if (timers[i].h.get() == h) timers.erase(timers.begin() + i); else ++i; } return kResultOk; }

    void idle() {
        if (dpy) while (XPending(dpy)) { XEvent ev; XNextEvent(dpy, &ev); }
        std::vector<FdH> f = fds;                                  // handlers may unregister themselves while running
        for (auto& e : f) {
            pollfd p{e.fd, POLLIN, 0};
            if (poll(&p, 1, 0) > 0 && (p.revents & POLLIN)) { e.h->onFDIsSet(e.fd); ++fdCalls; }
        }
        auto now = std::chrono::steady_clock::now();
        std::vector<TmH> t = timers;
        for (size_t i = 0; i < t.size(); ++i)
            if (now >= t[i].next) {
                for (auto& real : timers) if (real.h == t[i].h) real.next = now + std::chrono::milliseconds(real.ms);
                t[i].h->onTimer(); ++timerCalls;
            }
    }
};

static int x_error_ignore(Display*, XErrorEvent*) { return 0; }   // a plug-in's harmless X errors must not kill the sampler

struct Host {
    VST3::Hosting::Module::Ptr module;
    IPtr<PlugProvider> provider;
    IPtr<IComponent> comp;
    IPtr<IEditController> ctrl;
    FUnknownPtr<IAudioProcessor> proc;
    HostProcessData data;
    ParameterChanges changes;
    std::vector<ParameterInfo> params;
    std::vector<std::pair<ParamID, double>> pending;
    std::mutex lock;
    std::string name;
    Editor* editor = nullptr;
    int maxBlock = 512;
    bool stereoIn = true;
    bool instrument = false;                // "Instrument" sub-category: plays notes, no audio input
    EventList events{512};
    struct Note { int offset; int pitch; float vel; bool on; };
    std::vector<Note> notes;                // queued note events for the next process() call
    struct Handler* handler = nullptr;
};

// Knob moves made in the plug-in's own window arrive here and are passed to the audio processor in the next block.
struct Handler : public IComponentHandler {
    std::atomic<int32> refs{1};
    Host* h;
    explicit Handler(Host* host) : h(host) {}
    tresult PLUGIN_API queryInterface(const TUID _iid, void** obj) override {
        if (FUnknownPrivate::iidEqual(_iid, IComponentHandler::iid) || FUnknownPrivate::iidEqual(_iid, FUnknown::iid)) {
            addRef(); *obj = static_cast<IComponentHandler*>(this); return kResultOk; }
        *obj = nullptr; return kNoInterface;
    }
    uint32 PLUGIN_API addRef() override { return ++refs; }
    uint32 PLUGIN_API release() override { return --refs; }
    tresult PLUGIN_API beginEdit(ParamID) override { return kResultOk; }
    tresult PLUGIN_API performEdit(ParamID id, ParamValue v) override {
        std::lock_guard<std::mutex> g(h->lock); h->pending.emplace_back(id, v); return kResultOk; }
    tresult PLUGIN_API endEdit(ParamID) override { return kResultOk; }
    tresult PLUGIN_API restartComponent(int32) override { return kResultOk; }
};

static void copy_err(char* err, int len, const std::string& s) {
    if (err && len > 0) { std::strncpy(err, s.c_str(), len - 1); err[len - 1] = 0; }
}

extern "C" {

void* vh_open(const char* path, double sampleRate, int maxBlock, char* err, int errLen) {
    if (!g_host) { g_host = new HostApplication(); PluginContextFactory::instance().setPluginContext(g_host); }
    std::string e;
    auto module = VST3::Hosting::Module::create(path, e);
    if (!module) { copy_err(err, errLen, "could not load module: " + e); return nullptr; }
    auto factory = module->getFactory();
    factory.setHostContext(g_host);
    for (auto& ci : factory.classInfos()) {
        if (ci.category() != kVstAudioEffectClass) continue;
        auto h = new Host();
        h->module = module; h->name = ci.name(); h->maxBlock = maxBlock;
        h->provider = owned(new PlugProvider(factory, ci, true));
        if (!h->provider->initialize()) { delete h; copy_err(err, errLen, "plugin failed to initialise"); return nullptr; }
        h->comp = h->provider->getComponentPtr();
        h->ctrl = h->provider->getControllerPtr();
        h->proc = FUnknownPtr<IAudioProcessor>(h->comp);
        if (!h->proc || !h->ctrl) { delete h; copy_err(err, errLen, "not an audio effect with a controller"); return nullptr; }
        SpeakerArrangement st = SpeakerArr::kStereo;
        int nin = h->comp->getBusCount(kAudio, kInput), nout = h->comp->getBusCount(kAudio, kOutput);
        std::vector<SpeakerArrangement> ins(nin, SpeakerArr::kStereo), outs(nout, SpeakerArr::kStereo);
        h->proc->setBusArrangements(ins.data(), nin, outs.data(), nout);
        for (int i = 0; i < nin; ++i) h->comp->activateBus(kAudio, kInput, i, i == 0);
        for (int i = 0; i < nout; ++i) h->comp->activateBus(kAudio, kOutput, i, i == 0);
        h->stereoIn = nin > 0;
        h->instrument = ci.subCategoriesString().find("Instrument") != std::string::npos;
        int nev = h->comp->getBusCount(kEvent, kInput);
        for (int i = 0; i < nev; ++i) h->comp->activateBus(kEvent, kInput, i, i == 0);
        if (nev > 0) h->instrument = true;
        ProcessSetup setup{kRealtime, kSample32, maxBlock, sampleRate};
        if (h->proc->setupProcessing(setup) != kResultOk) { delete h; copy_err(err, errLen, "setupProcessing failed"); return nullptr; }
        h->comp->setActive(true);
        h->data.prepare(*h->comp, maxBlock, kSample32);
        h->data.processContext = nullptr;
        h->data.inputParameterChanges = &h->changes;
        h->data.inputEvents = &h->events;
        h->proc->setProcessing(true);
        h->handler = new Handler(h);
        h->ctrl->setComponentHandler(h->handler);
        int n = h->ctrl->getParameterCount();
        for (int i = 0; i < n; ++i) {
            ParameterInfo pi{};
            if (h->ctrl->getParameterInfo(i, pi) == kResultOk && !(pi.flags & ParameterInfo::kIsReadOnly) && !(pi.flags & ParameterInfo::kIsHidden)
                && !(pi.flags & ParameterInfo::kIsBypass) && !(pi.flags & ParameterInfo::kIsProgramChange))
                h->params.push_back(pi);
        }
        (void)st;
        return h;
    }
    copy_err(err, errLen, "no audio effect class in this module");
    return nullptr;
}

const char* vh_name(void* p) { return p ? static_cast<Host*>(p)->name.c_str() : ""; }
int vh_param_count(void* p) { return p ? (int)static_cast<Host*>(p)->params.size() : 0; }

int vh_param_title(void* p, int i, char* out, int len) {
    auto h = static_cast<Host*>(p);
    if (!h || i < 0 || i >= (int)h->params.size()) return 0;
    copy_err(out, len, VST3::StringConvert::convert(h->params[i].title));
    return 1;
}

double vh_get(void* p, int i) {
    auto h = static_cast<Host*>(p);
    if (!h || i < 0 || i >= (int)h->params.size()) return 0.0;
    return h->ctrl->getParamNormalized(h->params[i].id);
}

void vh_set(void* p, int i, double v) {
    auto h = static_cast<Host*>(p);
    if (!h || i < 0 || i >= (int)h->params.size()) return;
    v = v < 0 ? 0 : (v > 1 ? 1 : v);
    h->ctrl->setParamNormalized(h->params[i].id, v);
    std::lock_guard<std::mutex> g(h->lock);
    h->pending.emplace_back(h->params[i].id, v);
}

int vh_param_string(void* p, int i, char* out, int len) {
    auto h = static_cast<Host*>(p);
    if (!h || i < 0 || i >= (int)h->params.size()) return 0;
    String128 s{};
    ParamID id = h->params[i].id;
    if (h->ctrl->getParamStringByValue(id, h->ctrl->getParamNormalized(id), s) != kResultOk) return 0;
    std::string txt = VST3::StringConvert::convert(s);
    std::string units = VST3::StringConvert::convert(h->params[i].units);
    if (!units.empty()) txt += " " + units;
    copy_err(out, len, txt);
    return 1;
}

// in-place stereo processing of n samples (split into blocks of maxBlock)
int vh_is_instrument(void* p) { auto h = static_cast<Host*>(p); return h && h->instrument ? 1 : 0; }

// queue a note for the next vh_process call: offset = sample offset inside that call, vel 0-127; on = 1 note-on, 0 note-off
void vh_note(void* p, int offset, int pitch, int vel, int on) {
    auto h = static_cast<Host*>(p);
    if (!h) return;
    std::lock_guard<std::mutex> g(h->lock);
    h->notes.push_back({offset < 0 ? 0 : offset, pitch & 127, (vel & 127) / 127.0f, on != 0});
}

// a MIDI controller for an instrument: 0-127 = CC number (1 = mod wheel), 128 = channel aftertouch, 129 = pitch bend.
// VST3 has no MIDI controller events: the plug-in says (IMidiMapping) which parameter a controller drives, and we set that.
// Returns 1 if the plug-in maps this controller, 0 if not.
int vh_midi_controller(void* p, int controller, double value) {
    auto h = static_cast<Host*>(p);
    if (!h || !h->ctrl) return 0;
    FUnknownPtr<IMidiMapping> mm(h->ctrl);
    if (!mm) return 0;
    ParamID id = 0;
    if (mm->getMidiControllerAssignment(0, 0, (CtrlNumber)controller, id) != kResultOk) return 0;
    value = value < 0 ? 0 : (value > 1 ? 1 : value);
    h->ctrl->setParamNormalized(id, value);
    std::lock_guard<std::mutex> g(h->lock);
    h->pending.emplace_back(id, value);
    return 1;
}

int vh_process(void* p, float* L, float* R, int n) {
    auto h = static_cast<Host*>(p);
    if (!h) return 0;
    int done = 0;
    std::vector<Host::Note> notes;
    { std::lock_guard<std::mutex> g(h->lock); notes.swap(h->notes); }
    while (done < n) {
        int k = n - done < h->maxBlock ? n - done : h->maxBlock;
        h->events.clear();
        for (auto& nt : notes) {
            if (nt.offset < done || nt.offset >= done + k) continue;
            Event ev{};
            ev.busIndex = 0; ev.sampleOffset = nt.offset - done; ev.ppqPosition = 0; ev.flags = Event::kIsLive;
            if (nt.on) { ev.type = Event::kNoteOnEvent; ev.noteOn.channel = 0; ev.noteOn.pitch = nt.pitch; ev.noteOn.velocity = nt.vel; ev.noteOn.noteId = -1; }
            else { ev.type = Event::kNoteOffEvent; ev.noteOff.channel = 0; ev.noteOff.pitch = nt.pitch; ev.noteOff.velocity = 0.0f; ev.noteOff.noteId = -1; }
            h->events.addEvent(ev);
        }
        {
            std::lock_guard<std::mutex> g(h->lock);
            for (auto& pv : h->pending) {
                int32 idx = 0;
                if (auto q = h->changes.addParameterData(pv.first, idx)) { int32 pi = 0; q->addPoint(0, pv.second, pi); }
            }
            h->pending.clear();
        }
        if (h->data.numInputs > 0 && h->data.inputs[0].numChannels >= 2) {
            std::memcpy(h->data.inputs[0].channelBuffers32[0], L + done, k * sizeof(float));
            std::memcpy(h->data.inputs[0].channelBuffers32[1], R + done, k * sizeof(float));
        }
        h->data.numSamples = k;
        h->proc->process(h->data);
        h->changes.clearQueue();
        if (h->data.numOutputs > 0 && h->data.outputs[0].numChannels >= 2) {
            std::memcpy(L + done, h->data.outputs[0].channelBuffers32[0], k * sizeof(float));
            std::memcpy(R + done, h->data.outputs[0].channelBuffers32[1], k * sizeof(float));
        }
        done += k;
    }
    std::vector<Host::Note> later;
    for (auto& nt : notes) if (nt.offset >= n) later.push_back({nt.offset - n, nt.pitch, nt.vel, nt.on});
    if (!later.empty()) { std::lock_guard<std::mutex> g(h->lock); h->notes.insert(h->notes.begin(), later.begin(), later.end()); }
    return 1;
}

// Opens the plug-in's own window. parent = an X11 window to embed into (0 = a new top-level window at x, y).
// Returns the X11 window id (0 = this plug-in has no editor or no X display). Size in *w, *h.
unsigned long vh_editor_open(void* p, unsigned long parent, int x, int y, int* w, int* hgt) {
    auto h = static_cast<Host*>(p);
    if (!h || h->editor) return h && h->editor ? h->editor->win : 0;
    IPtr<IPlugView> view = owned(h->ctrl->createView(ViewType::kEditor));
    if (!view || view->isPlatformTypeSupported(kPlatformTypeX11EmbedWindowID) != kResultTrue) return 0;
    auto ed = new Editor();
    XSetErrorHandler(x_error_ignore);
    ed->dpy = XOpenDisplay(nullptr);
    if (!ed->dpy) { delete ed; return 0; }
    ViewRect r{};
    view->getSize(&r);
    ed->width = r.getWidth() > 0 ? r.getWidth() : 640; ed->height = r.getHeight() > 0 ? r.getHeight() : 400;
    Window root = parent ? (Window)parent : DefaultRootWindow(ed->dpy);
    ed->win = XCreateSimpleWindow(ed->dpy, root, x, y, ed->width, ed->height, 0, 0, 0);
    XStoreName(ed->dpy, ed->win, h->name.c_str());
    XMapRaised(ed->dpy, ed->win); XSync(ed->dpy, False);
    view->setFrame(ed);
    if (view->attached((void*)ed->win, kPlatformTypeX11EmbedWindowID) != kResultOk) {
        XDestroyWindow(ed->dpy, ed->win); XCloseDisplay(ed->dpy); delete ed; return 0; }
    ed->view = view;
    h->editor = ed;
    if (w) *w = ed->width;
    if (hgt) *hgt = ed->height;
    return ed->win;
}

// zoom: ask the plug-in to draw itself at `factor` (1.0 = its normal size). Returns 1 if it supports this.
// The plug-in then resizes its window (through IPlugFrame::resizeView); read the new size with vh_editor_size.
int vh_editor_scale(void* p, float factor) {
    auto h = static_cast<Host*>(p);
    if (!h || !h->editor) return 0;
    FUnknownPtr<IPlugViewContentScaleSupport> cs(h->editor->view);
    if (!cs) return 0;
    if (cs->setContentScaleFactor(factor) != kResultTrue) return 0;
    ViewRect r{};
    if (h->editor->view->getSize(&r) == kResultOk && r.getWidth() > 0 &&
        (r.getWidth() != h->editor->width || r.getHeight() != h->editor->height)) {
        h->editor->width = r.getWidth(); h->editor->height = r.getHeight();
        XResizeWindow(h->editor->dpy, h->editor->win, h->editor->width, h->editor->height); XFlush(h->editor->dpy);
        h->editor->view->onSize(&r);
    }
    return 1;
}

int vh_editor_size(void* p, int* w, int* hgt) {
    auto h = static_cast<Host*>(p);
    if (!h || !h->editor) return 0;
    *w = h->editor->width; *hgt = h->editor->height; return 1;
}

// move the plug-in window inside its parent (used for scrolling: the parent is a clipping viewport)
void vh_editor_move(void* p, int x, int y) {
    auto h = static_cast<Host*>(p);
    if (!h || !h->editor) return;
    XMoveWindow(h->editor->dpy, h->editor->win, x, y); XFlush(h->editor->dpy);
}

int vh_editor_handlers(void* p) { auto h = static_cast<Host*>(p); return h && h->editor ? (int)(h->editor->fds.size() * 1000000 + h->editor->timers.size() * 100000 + h->editor->fdCalls) : -1; }

void vh_editor_idle(void* p) { auto h = static_cast<Host*>(p); if (h && h->editor) h->editor->idle(); }

void vh_editor_close(void* p) {
    auto h = static_cast<Host*>(p);
    if (!h || !h->editor) return;
    auto ed = h->editor; h->editor = nullptr;
    ed->view->removed(); ed->view->setFrame(nullptr); ed->view = nullptr;
    ed->fds.clear(); ed->timers.clear();
    XDestroyWindow(ed->dpy, ed->win); XCloseDisplay(ed->dpy);
    delete ed;
}

void vh_close(void* p) {
    auto h = static_cast<Host*>(p);
    if (!h) return;
    vh_editor_close(p);
    h->proc->setProcessing(false);
    h->comp->setActive(false);
    h->data.unprepare();
    h->ctrl->setComponentHandler(nullptr);
    h->proc = nullptr; h->ctrl = nullptr; h->comp = nullptr; h->provider = nullptr;
    delete h->handler;
    delete h;
}

// ---------------------------------------------------------------------------------------------
// A plain X11 window for the sampler's own screen (used when the sampler runs under X so that
// plug-in windows can be shown inside it). No window manager is needed: the window sits at x, y.
// ---------------------------------------------------------------------------------------------
static Display* s_dpy = nullptr;
static Window s_win = 0;
static GC s_gc;
static int s_w = 0, s_h = 0;

unsigned long xs_open(int w, int hgt, int x, int y, const char* title) {
    XSetErrorHandler(x_error_ignore);
    if (!s_dpy) s_dpy = XOpenDisplay(nullptr);
    if (!s_dpy) return 0;
    XSetWindowAttributes a{};
    a.override_redirect = True; a.background_pixel = BlackPixel(s_dpy, DefaultScreen(s_dpy));
    a.event_mask = ButtonPressMask | ButtonReleaseMask | ButtonMotionMask | ExposureMask | StructureNotifyMask;
    s_win = XCreateWindow(s_dpy, DefaultRootWindow(s_dpy), x, y, w, hgt, 0, CopyFromParent, InputOutput, CopyFromParent,
                          CWOverrideRedirect | CWBackPixel | CWEventMask, &a);
    XStoreName(s_dpy, s_win, title ? title : "sampler");
    s_gc = XCreateGC(s_dpy, s_win, 0, nullptr);
    XMapRaised(s_dpy, s_win); XSync(s_dpy, False);
    s_w = w; s_h = hgt;
    return s_win;
}

// a plain child window of the sampler window: the viewport that clips a plug-in window larger than the screen
unsigned long xs_child(int x, int y, int w, int hgt) {
    if (!s_dpy || !s_win) return 0;
    // a top-level, override-redirect window placed over the sampler window (x, y are screen coordinates; the sampler
    // window sits at 0, 0). A real child of the sampler window would work for showing the plug-in, but some plug-ins
    // (JUCE ones) then ignore zoom changes, so the viewport hangs off the root window instead.
    XSetWindowAttributes a{};
    a.override_redirect = True; a.background_pixel = BlackPixel(s_dpy, DefaultScreen(s_dpy));
    Window c = XCreateWindow(s_dpy, DefaultRootWindow(s_dpy), x, y, w > 0 ? w : 1, hgt > 0 ? hgt : 1, 0, CopyFromParent,
                             InputOutput, CopyFromParent, CWOverrideRedirect | CWBackPixel, &a);
    XMapRaised(s_dpy, c); XSync(s_dpy, False);
    return c;
}

void xs_place(unsigned long w, int x, int y, int width, int hgt) {
    if (s_dpy && w) { XMoveResizeWindow(s_dpy, (Window)w, x, y, width > 0 ? width : 1, hgt > 0 ? hgt : 1); XSync(s_dpy, False); }
}

void xs_destroy(unsigned long w) { if (s_dpy && w) { XDestroyWindow(s_dpy, (Window)w); XSync(s_dpy, False); } }

int xs_screen_size(int* w, int* hgt) {
    if (!s_dpy) s_dpy = XOpenDisplay(nullptr);
    if (!s_dpy) return 0;
    *w = DisplayWidth(s_dpy, DefaultScreen(s_dpy)); *hgt = DisplayHeight(s_dpy, DefaultScreen(s_dpy));
    return 1;
}

// bgrx: w*h*4 bytes (B, G, R, unused) - the usual 24-bit TrueColor layout
void xs_put(const unsigned char* bgrx, int w, int hgt) {
    if (!s_dpy || !s_win) return;
    XImage* img = XCreateImage(s_dpy, DefaultVisual(s_dpy, DefaultScreen(s_dpy)), 24, ZPixmap, 0, (char*)bgrx, w, hgt, 32, w * 4);
    if (!img) return;
    XPutImage(s_dpy, s_win, s_gc, img, 0, 0, 0, 0, w, hgt);
    img->data = nullptr; XDestroyImage(img);
    XFlush(s_dpy);
}

// next pointer / touch event: kind 1 = down, 2 = move, 3 = up. Returns 0 when there is none.
int xs_event(int* kind, int* x, int* y) {
    if (!s_dpy) return 0;
    while (XPending(s_dpy)) {
        XEvent ev; XNextEvent(s_dpy, &ev);
        if (ev.type == ButtonPress && ev.xbutton.button == Button1) { *kind = 1; *x = ev.xbutton.x; *y = ev.xbutton.y; return 1; }
        if (ev.type == MotionNotify) { *kind = 2; *x = ev.xmotion.x; *y = ev.xmotion.y; return 1; }
        if (ev.type == ButtonRelease && ev.xbutton.button == Button1) { *kind = 3; *x = ev.xbutton.x; *y = ev.xbutton.y; return 1; }
    }
    return 0;
}

// copy what is on screen in the sampler window (including any plug-in window inside it) into bgrx
int xs_grab(unsigned char* bgrx, int w, int hgt) {
    if (!s_dpy || !s_win) return 0;
    XSync(s_dpy, False);
    XImage* img = XGetImage(s_dpy, DefaultRootWindow(s_dpy), 0, 0, w, hgt, AllPlanes, ZPixmap);   // the screen as seen, plug-in windows included
    if (!img) return 0;
    for (int yy = 0; yy < hgt; ++yy)
        for (int xx = 0; xx < w; ++xx) {
            unsigned long px = XGetPixel(img, xx, yy);
            unsigned char* o = bgrx + (yy * w + xx) * 4;
            o[0] = px & 0xff; o[1] = (px >> 8) & 0xff; o[2] = (px >> 16) & 0xff; o[3] = 0;
        }
    XDestroyImage(img);
    return 1;
}

}  // extern "C"
