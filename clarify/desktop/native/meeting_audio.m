#import <CoreAudio/AudioHardwareTapping.h>
#import <CoreAudio/CATapDescription.h>
#import <Foundation/Foundation.h>

#include <math.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdlib.h>

enum { PcmRate = 16000, RingFrames = 2 * PcmRate, SignalFrames = 160 };

typedef struct {
    AudioObjectID tap;
    AudioObjectID device;
    AudioDeviceIOProcID proc;
    bool started;
    double sampleRate;
    // Only the Core Audio callback writes samples. Only the meeting consumer
    // advances readIndex. Release/acquire pairs protect samples across threads.
    _Atomic uint64_t readIndex;
    _Atomic uint64_t writeIndex;
    _Atomic bool overflow;
    _Atomic bool invalid;
    float ring[RingFrames];
    double step;
    double remaining;
    double sum;
    double b0, b1, b2, a1, a2, z1, z2;
    unsigned signalFrames;
} MeetingTap;

static double tap_sample_rate(AudioObjectID tap) {
    AudioObjectPropertyAddress address = {
        kAudioTapPropertyFormat, kAudioObjectPropertyScopeGlobal, kAudioObjectPropertyElementMain
    };
    AudioStreamBasicDescription format = {0};
    UInt32 size = sizeof(format);
    if (AudioObjectGetPropertyData(tap, &address, 0, NULL, &size, &format) != noErr
        || format.mFormatID != kAudioFormatLinearPCM
        || !(format.mFormatFlags & kAudioFormatFlagIsFloat)
        || !(format.mFormatFlags & kAudioFormatFlagIsPacked)
        || (format.mFormatFlags & kAudioFormatFlagIsBigEndian)
        || format.mBitsPerChannel != 32 || format.mBytesPerFrame != sizeof(float)
        || format.mChannelsPerFrame != 1 || !isfinite(format.mSampleRate)
        || format.mSampleRate < PcmRate) return 0;
    return format.mSampleRate;
}

static OSStatus receive_audio(AudioObjectID device, const AudioTimeStamp *now,
                              const AudioBufferList *input, const AudioTimeStamp *inputTime,
                              AudioBufferList *output, const AudioTimeStamp *outputTime,
                              void *context) {
    MeetingTap *tap = context;
    if (!input || input->mNumberBuffers == 0) return noErr;
    const AudioBuffer *buffer = &input->mBuffers[0];
    if (input->mNumberBuffers != 1 || buffer->mNumberChannels != 1
        || buffer->mDataByteSize % sizeof(float)) {
        atomic_store_explicit(&tap->invalid, true, memory_order_relaxed);
        return noErr;
    }
    if (!buffer->mData) return noErr;
    const float *samples = buffer->mData;
    const uint64_t head = atomic_load_explicit(&tap->readIndex, memory_order_acquire);
    uint64_t tail = atomic_load_explicit(&tap->writeIndex, memory_order_relaxed);
    for (size_t index = 0; index < buffer->mDataByteSize / sizeof(float); index++) {
        // Low-pass before reducing the sample rate. Carry filter and fractional
        // frame state across callbacks, including 44.1 kHz output devices.
        double sample = isfinite(samples[index]) ? samples[index] : 0;
        double filtered = tap->b0 * sample + tap->z1;
        tap->z1 = tap->b1 * sample - tap->a1 * filtered + tap->z2;
        tap->z2 = tap->b2 * sample - tap->a2 * filtered;
        if (tap->remaining > 1) {
            tap->sum += filtered;
            tap->remaining -= 1;
            continue;
        }
        if (tail - head < RingFrames) {
            tap->ring[tail++ % RingFrames] = (tap->sum + filtered * tap->remaining) / tap->step;
        } else {
            atomic_store_explicit(&tap->overflow, true, memory_order_relaxed);
        }
        tap->sum = filtered * (1 - tap->remaining);
        tap->remaining += tap->step - 1;
    }
    atomic_store_explicit(&tap->writeIndex, tail, memory_order_release);
    return noErr;
}

__attribute__((visibility("default")))
void clarify_meeting_tap_close(MeetingTap *tap) {
    if (!tap) return;
    if (tap->started) AudioDeviceStop(tap->device, tap->proc);
    if (tap->proc) AudioDeviceDestroyIOProcID(tap->device, tap->proc);
    if (tap->device != kAudioObjectUnknown) AudioHardwareDestroyAggregateDevice(tap->device);
    if (@available(macOS 14.2, *)) {
        if (tap->tap != kAudioObjectUnknown) AudioHardwareDestroyProcessTap(tap->tap);
    }
    free(tap);
}

API_AVAILABLE(macos(14.2))
static MeetingTap *open_tap(CATapDescription *description, OSStatus *status) {
    NSDictionary *config = nil;
    MeetingTap *tap = calloc(1, sizeof(*tap));
    if (!tap) {
        *status = kAudioHardwareUnspecifiedError;
        return NULL;
    }
    atomic_init(&tap->readIndex, 0);
    atomic_init(&tap->writeIndex, 0);
    atomic_init(&tap->overflow, false);
    atomic_init(&tap->invalid, false);
    description.name = @"Clarify meeting audio";
    description.privateTap = YES;
    description.muteBehavior = CATapUnmuted;
    *status = AudioHardwareCreateProcessTap(description, &tap->tap);
    if (*status != noErr) goto fail;
    tap->sampleRate = tap_sample_rate(tap->tap);
    if (!tap->sampleRate) {
        *status = kAudioDeviceUnsupportedFormatError;
        goto fail;
    }
    tap->step = tap->remaining = tap->sampleRate / PcmRate;
    // A second-order Butterworth low-pass at 6 kHz limits aliasing in speech.
    double k = tan(M_PI * 6000 / tap->sampleRate);
    double norm = 1 / (1 + M_SQRT2 * k + k * k);
    tap->b0 = tap->b2 = k * k * norm;
    tap->b1 = 2 * tap->b0;
    tap->a1 = 2 * (k * k - 1) * norm;
    tap->a2 = (1 - M_SQRT2 * k + k * k) * norm;
    config = @{
        @kAudioAggregateDeviceNameKey: @"Clarify meeting audio",
        @kAudioAggregateDeviceUIDKey: NSUUID.UUID.UUIDString,
        @kAudioAggregateDeviceIsPrivateKey: @YES,
        @kAudioAggregateDeviceTapAutoStartKey: @YES,
        @kAudioAggregateDeviceTapListKey: @[@{
            @kAudioSubTapUIDKey: description.UUID.UUIDString,
            @kAudioSubTapDriftCompensationKey: @YES,
        }],
    };
    *status = AudioHardwareCreateAggregateDevice((__bridge CFDictionaryRef)config, &tap->device);
    if (*status != noErr) goto fail;
    *status = AudioDeviceCreateIOProcID(tap->device, receive_audio, tap, &tap->proc);
    if (*status != noErr) goto fail;
    *status = AudioDeviceStart(tap->device, tap->proc);
    if (*status != noErr) goto fail;
    tap->started = true;
    return tap;
fail:
    clarify_meeting_tap_close(tap);
    return NULL;
}

__attribute__((visibility("default")))
MeetingTap *clarify_meeting_tap_open(OSStatus *status) {
    @autoreleasepool {
        if (@available(macOS 14.2, *)) {
            return open_tap([[CATapDescription alloc] initMonoGlobalTapButExcludeProcesses:@[]], status);
        }
    }
    *status = kAudioHardwareUnsupportedOperationError;
    return NULL;
}

// Keep the tap PCM separate and report how many frames were read. The caller
// zero-initializes the system buffer so a short read cannot supply stale samples.
__attribute__((visibility("default")))
int clarify_meeting_tap_read(MeetingTap *tap, int16_t *mixed, int16_t *system,
                             size_t frames, size_t *valid) {
    *valid = 0;
    if (atomic_load_explicit(&tap->invalid, memory_order_relaxed)
        || tap_sample_rate(tap->tap) != tap->sampleRate) return -1;
    if (atomic_load_explicit(&tap->overflow, memory_order_relaxed)) return -2;
    const uint64_t tail = atomic_load_explicit(&tap->writeIndex, memory_order_acquire);
    uint64_t head = atomic_load_explicit(&tap->readIndex, memory_order_relaxed);
    if (tail == head) return -3;
    // The microphones and output devices have separate clocks. Limit the delay
    // between them, including the lead while the renderer starts its worklet.
    const size_t maxLag = PcmRate / 10;
    if (tail - head > frames + maxLag) head = tail - frames - maxLag;
    size_t count = (tail - head < frames) ? tail - head : frames;
    for (size_t index = 0; index < count; index++, head++) {
        const float remote = tap->ring[head % RingFrames];
        if (tap->signalFrames < SignalFrames && fabsf(remote) >= 0.01f) tap->signalFrames++;
        system[index] = (int16_t)lrintf(fmaxf(-32768, fminf(32767, remote * 32767)));
        const float sum = mixed[index] + remote * 32767;
        mixed[index] = (int16_t)lrintf(fmaxf(-32768, fminf(32767, sum)));
    }
    atomic_store_explicit(&tap->readIndex, head, memory_order_release);
    *valid = count;
    return tap->signalFrames >= SignalFrames;
}
