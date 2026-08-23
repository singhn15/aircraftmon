<script setup>
import { ref } from 'vue'

const API_BASE_URL = '/api'

const aircraft = [
    { 
        hex: 'A06796', 
        name: '1967 DE HAVILLAND DHC-6 Twin Otter',
        status: ref(''),
        loading: ref(false),
        error: ref(null),
        isTracking: ref(false),
        state: ref(null),
        altitude: ref(null),
        verticalSpeed: ref(null),
        groundSpeed: ref(null),
        groundTrack: ref(null),
        latitude: ref(null),
        longitude: ref(null),
        lastUpdate: ref(null)
    },
    { 
        hex: 'ACBC30', 
        name: '1973 90 King Air BEECH',
        status: ref(''),
        loading: ref(false),
        error: ref(null),
        isTracking: ref(false),
        state: ref(null),
        altitude: ref(null),
        verticalSpeed: ref(null),
        groundSpeed: ref(null),
        groundTrack: ref(null),
        latitude: ref(null),
        longitude: ref(null),
        lastUpdate: ref(null)
    },
    { 
        hex: 'A9E236', 
        name: 'Test Plane',
        status: ref(''),
        loading: ref(false),
        error: ref(null),
        isTracking: ref(false),
        state: ref(null),
        altitude: ref(null),
        verticalSpeed: ref(null),
        groundSpeed: ref(null),
        groundTrack: ref(null),
        latitude: ref(null),
        longitude: ref(null),
        lastUpdate: ref(null)
    }
]

async function startTracking(plane) {
    if (plane.loading.value) return

    try {
        plane.loading.value = true
        plane.error.value = null

        // Actually start the tracker on the backend
        const response = await fetch(`${API_BASE_URL}/aircraft`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ hex: plane.hex })
        })
        if (!response.ok) {
            throw new Error('Failed to start tracking')
        }

        plane.status.value = 'Started tracking'
        plane.isTracking.value = true
        startPolling(plane)
    } catch (e) {
        plane.error.value = 'Failed to track aircraft'
        plane.status.value = ''
        plane.isTracking.value = false
        console.error(e)
    } finally {
        plane.loading.value = false
    }
}

async function stopTracking(hex) {
    try {
        const response = await fetch(`${API_BASE_URL}/stop/${hex}`, {
            method: 'POST'
        });
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return 'Stopped tracking aircraft';
    } catch (error) {
        console.error('Error stopping aircraft tracking:', error);
        throw error;
    }
}

async function handleStopTracking(plane) {
    if (plane.loading.value) return

    try {
        plane.loading.value = true
        plane.error.value = null
        const result = await stopTracking(plane.hex)
        console.log('Stop tracking result:', result)
        plane.status.value = result
        plane.isTracking.value = false
        plane.state.value = null
        plane.altitude.value = null
        plane.verticalSpeed.value = null
        plane.groundSpeed.value = null
        plane.lastUpdate.value = null
    } catch (e) {
        plane.error.value = 'Failed to stop tracking'
        console.error(e)
    } finally {
        plane.loading.value = false
    }
}

async function startPolling(plane) {
    let consecutiveErrors = 0
    while (plane.isTracking.value) {
        try {
            const response = await fetch(`${API_BASE_URL}/status/${plane.hex}`)
            if (response.status === 404) {
                consecutiveErrors++
                if (consecutiveErrors >= 2) {
                    // If we get multiple 404s, the tracking has definitely stopped
                    plane.isTracking.value = false
                    plane.status.value = 'Tracking stopped'
                    plane.state.value = null
                    plane.altitude.value = null
                    plane.verticalSpeed.value = null
                    plane.groundSpeed.value = null
                    plane.groundTrack.value = null
                    plane.latitude.value = null
                    plane.longitude.value = null
                    plane.lastUpdate.value = null
                    break
                }
            } else {
                consecutiveErrors = 0 // Reset error counter on success
                const data = await response.json()
                if (data) {
                    plane.state.value = data.state
                    plane.altitude.value = data.altitude_agl
                    plane.verticalSpeed.value = data.vertical_speed
                    plane.groundSpeed.value = data.ground_speed
                    plane.groundTrack.value = data.ground_track
                    plane.latitude.value = data.latitude
                    plane.longitude.value = data.longitude
                    plane.lastUpdate.value = new Date().toLocaleTimeString()
                }
            }
        } catch (error) {
            console.error('Error polling aircraft status:', error)
            consecutiveErrors++
            if (consecutiveErrors >= 3) {
                // If we get multiple errors, assume tracking has stopped
                plane.isTracking.value = false
                plane.status.value = 'Tracking stopped due to errors'
                plane.state.value = null
                plane.altitude.value = null
                plane.verticalSpeed.value = null
                plane.groundSpeed.value = null
                plane.groundTrack.value = null
                plane.latitude.value = null
                plane.longitude.value = null
                plane.lastUpdate.value = null
                break
            }
        }
        await new Promise(resolve => setTimeout(resolve, 10000)) // Poll every 10 seconds
    }
}

async function autoStartTracking() {
    aircraft.forEach(plane => {
        if (!plane.isTracking.value) {
          startTracking(plane)
        }
    })
}

autoStartTracking()
</script>

<template>
    <div class="min-h-screen py-8">
        <h1 class="text-3xl font-bold text-white text-center mb-8">Aircraft Monitor</h1>
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div v-for="plane in aircraft" :key="plane.hex" 
                    class="bg-gray-800 rounded-lg shadow-xl overflow-hidden border border-gray-700 hover:border-gray-600 transition-all duration-300">
                    <div class="p-6">
                        <div class="flex flex-col items-center text-center">
                            <h3 class="text-xl font-semibold text-white">{{ plane.name }}</h3>
                            <span class="text-sm text-gray-400 mt-1 font-mono">Hex: {{ plane.hex }}</span>
                        </div>

                        <div class="mt-6 space-y-4">
                            <div :class="[
                                'p-4 rounded-md text-center font-medium transition-colors duration-300',
                                plane.isTracking.value 
                                    ? 'bg-emerald-900/50 text-emerald-400 border border-emerald-700'
                                    : 'bg-gray-700/50 text-gray-300 border border-gray-600'
                            ]">
                                {{ plane.status }}
                            </div>

                            <div v-if="plane.isTracking.value" class="bg-gray-700/30 rounded-lg p-4 border border-gray-700">
                                <div class="space-y-3">
                                    <div class="flex justify-between items-center py-2 border-b border-gray-600/50">
                                        <span class="text-gray-400">State</span>
                                        <span class="text-gray-200 font-medium">{{ plane.state?.value || 'Unknown' }}</span>
                                    </div>
                                    <div class="flex justify-between items-center py-2 border-b border-gray-600/50">
                                        <span class="text-gray-400">Altitude</span>
                                        <span class="text-gray-200 font-medium">{{ plane.altitude?.value ? `${plane.altitude.value} ft AGL` : 'Unknown' }}</span>
                                    </div>
                                    <div class="flex justify-between items-center py-2 border-b border-gray-600/50">
                                        <span class="text-gray-400">Vertical Speed</span>
                                        <span class="text-gray-200 font-medium">{{ plane.verticalSpeed?.value ? `${plane.verticalSpeed.value} ft/min` : 'Unknown' }}</span>
                                    </div>
                                    <div class="flex justify-between items-center py-2 border-b border-gray-600/50">
                                        <span class="text-gray-400">Ground Speed</span>
                                        <span class="text-gray-200 font-medium">{{ plane.groundSpeed?.value ? `${plane.groundSpeed.value} kts` : 'Unknown' }}</span>
                                    </div>
                                    <div class="flex justify-between items-center py-2 border-b border-gray-600/50">
                                        <span class="text-gray-400">Ground Track</span>
                                        <span class="text-gray-200 font-medium">{{ plane.groundTrack?.value ? `${plane.groundTrack.value} °` : 'Unknown' }}</span>
                                    </div>
                                    <div class="flex justify-between items-center py-2 border-b border-gray-600/50">
                                        <span class="text-gray-400">Position</span>
                                        <span class="text-gray-200 font-medium">{{ plane.latitude?.value && plane.longitude?.value ? `${plane.latitude.value.toFixed(3)}, ${plane.longitude.value.toFixed(3)}` : 'Unknown' }}</span>
                                    </div>
                                </div>
                                <div v-if="plane.lastUpdate?.value" class="mt-3 text-center text-sm text-gray-500">
                                    Last updated: {{ plane.lastUpdate.value }}
                                </div>
                            </div>

                            <div v-if="plane.error && plane.error.value" 
                                class="p-3 bg-red-900/30 border border-red-800 rounded-md text-red-400 text-sm">
                                {{ plane.error.value }}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>

<style scoped>
/* Scoped styles if needed */
</style> 