#include <Arduino.h>
#include <NimBLEDevice.h>

static const char* DEVICE_NAME = "AirClip-Relay";
static const char* SERVICE_UUID = "7b1f0001-8f5d-4d3a-9f4c-1d76b8f0a901";
static const char* RX_UUID = "7b1f0002-8f5d-4d3a-9f4c-1d76b8f0a901";
static const char* TX_UUID = "7b1f0003-8f5d-4d3a-9f4c-1d76b8f0a901";
static const size_t RELAY_QUEUE_CAPACITY = 256;
static const uint32_t RELAY_NOTIFY_DRAIN_INTERVAL_MS = 2;
static const uint32_t RELAY_INDICATE_DRAIN_INTERVAL_MS = 12;

#ifndef RELAY_USE_NOTIFY
#define RELAY_USE_NOTIFY 1
#endif

static NimBLECharacteristic* txCharacteristic = nullptr;
static uint32_t connectedClients = 0;
static std::string relayQueue[RELAY_QUEUE_CAPACITY];
static size_t relayQueueHead = 0;
static size_t relayQueueTail = 0;
static size_t relayQueueSize = 0;
static uint32_t lastRelayDrainMs = 0;

struct FrameSummary {
  bool binary;
  uint8_t version;
  uint8_t kind;
  uint16_t index;
  uint16_t total;
  char messageId[9];
  char hash[13];
};

// Read little-endian 16-bit fields from protocol frames without alignment assumptions.
static uint16_t readLe16(const uint8_t* data) {
  return static_cast<uint16_t>(data[0]) | (static_cast<uint16_t>(data[1]) << 8);
}

// Convert a byte prefix into printable hex for safe serial diagnostics.
static void hexPrefix(const uint8_t* data, size_t count, char* output, size_t outputSize) {
  static const char* hex = "0123456789abcdef";
  size_t maxBytes = (outputSize - 1) / 2;
  size_t bytes = count < maxBytes ? count : maxBytes;
  for (size_t index = 0; index < bytes; index++) {
    output[index * 2] = hex[(data[index] >> 4) & 0x0F];
    output[index * 2 + 1] = hex[data[index] & 0x0F];
  }
  output[bytes * 2] = '\0';
}

// Summarize AirClip binary frames without printing clipboard contents.
static FrameSummary summarizeFrame(const std::string& value) {
  FrameSummary summary = {};
  summary.index = 0;
  summary.total = 0;
  strncpy(summary.messageId, "-", sizeof(summary.messageId));
  strncpy(summary.hash, "-", sizeof(summary.hash));

  const uint8_t* data = reinterpret_cast<const uint8_t*>(value.data());
  size_t size = value.size();
  if (size < 40 || data[0] != 'A' || data[1] != 'C') {
    return summary;
  }

  summary.binary = true;
  summary.version = data[2];
  summary.kind = data[3];
  hexPrefix(data + 20, 4, summary.messageId, sizeof(summary.messageId));
  summary.index = readLe16(data + 36);
  summary.total = readLe16(data + 38);
  if (summary.kind == 1 && summary.index == 0 && size >= 86) {
    hexPrefix(data + 54, 6, summary.hash, sizeof(summary.hash));
  }
  return summary;
}

// Print concise relay diagnostics that can be matched with desktop logs.
static void logFrameEvent(const char* event, const std::string& value) {
  FrameSummary summary = summarizeFrame(value);
  if (!summary.binary) {
    Serial.printf("%s legacy/unknown frame bytes=%u queued=%u\n",
                  event,
                  static_cast<unsigned int>(value.size()),
                  static_cast<unsigned int>(relayQueueSize));
    return;
  }

  Serial.printf("%s kind=%u v=%u message=%s frame=%u/%u bytes=%u hash=%s queued=%u\n",
                event,
                static_cast<unsigned int>(summary.kind),
                static_cast<unsigned int>(summary.version),
                summary.messageId,
                static_cast<unsigned int>(summary.index + 1),
                static_cast<unsigned int>(summary.total),
                static_cast<unsigned int>(value.size()),
                summary.hash,
                static_cast<unsigned int>(relayQueueSize));
}

// Queue frames outside BLE callbacks so large clipboard bursts do not overload indications.
static bool enqueueRelayFrame(const std::string& value) {
  if (relayQueueSize >= RELAY_QUEUE_CAPACITY) {
    return false;
  }

  relayQueue[relayQueueTail] = value;
  relayQueueTail = (relayQueueTail + 1) % RELAY_QUEUE_CAPACITY;
  relayQueueSize++;
  return true;
}

// Pop the oldest queued frame while preserving write order between desktop agents.
static bool dequeueRelayFrame(std::string& value) {
  if (relayQueueSize == 0) {
    return false;
  }

  value = relayQueue[relayQueueHead];
  relayQueue[relayQueueHead].clear();
  relayQueueHead = (relayQueueHead + 1) % RELAY_QUEUE_CAPACITY;
  relayQueueSize--;
  return true;
}

// Return the pacing interval for the selected relay delivery mode.
static uint32_t relayDrainIntervalMs() {
  return RELAY_USE_NOTIFY ? RELAY_NOTIFY_DRAIN_INTERVAL_MS : RELAY_INDICATE_DRAIN_INTERVAL_MS;
}

// Drain queued frames at a controlled pace to keep the BLE stack responsive.
static void drainRelayQueue() {
  if (txCharacteristic == nullptr || connectedClients == 0 || relayQueueSize == 0) {
    return;
  }

  uint32_t now = millis();
  if (now - lastRelayDrainMs < relayDrainIntervalMs()) {
    return;
  }
  lastRelayDrainMs = now;

  std::string value;
  if (!dequeueRelayFrame(value)) {
    return;
  }

  txCharacteristic->setValue(reinterpret_cast<const uint8_t*>(value.data()), value.size());
  // Keep indication as the default and allow a compile-time notify fallback for comparison.
#if RELAY_USE_NOTIFY
  txCharacteristic->notify();
#else
  txCharacteristic->indicate();
#endif
  logFrameEvent("relayed", value);
}

class RelayServerCallbacks : public NimBLEServerCallbacks {
 public:
  // Keep advertising available so the second computer can join the same relay.
  void onConnect(NimBLEServer* server, NimBLEConnInfo& connInfo) override {
    connectedClients++;
    Serial.printf("client connected, total=%u\n", connectedClients);
    NimBLEDevice::startAdvertising();
  }

  // Track connection count for diagnostics only; desktop agents do deduplication.
  void onDisconnect(NimBLEServer* server, NimBLEConnInfo& connInfo, int reason) override {
    if (connectedClients > 0) {
      connectedClients--;
    }
    Serial.printf("client disconnected, total=%u\n", connectedClients);
    NimBLEDevice::startAdvertising();
  }
};

class RelayRxCallbacks : public NimBLECharacteristicCallbacks {
 public:
  // Queue each complete desktop frame without inspecting clipboard contents.
  void onWrite(NimBLECharacteristic* characteristic, NimBLEConnInfo& connInfo) override {
    std::string value = characteristic->getValue();
    if (value.empty() || txCharacteristic == nullptr) {
      return;
    }

    if (!enqueueRelayFrame(value)) {
      Serial.printf("relay queue full, dropped %u bytes\n", static_cast<unsigned int>(value.size()));
      return;
    }
    logFrameEvent("queued", value);
  }
};

// Configure the BLE GATT service used by both desktop agents.
static void setupBleRelay() {
  NimBLEDevice::init(DEVICE_NAME);
  NimBLEDevice::setPower(ESP_PWR_LVL_P9);
  NimBLEDevice::setMTU(247);

  NimBLEServer* server = NimBLEDevice::createServer();
  server->setCallbacks(new RelayServerCallbacks());

  NimBLEService* service = server->createService(SERVICE_UUID);
  txCharacteristic = service->createCharacteristic(
      TX_UUID,
      NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY | NIMBLE_PROPERTY::INDICATE);
  txCharacteristic->setValue("");

  NimBLECharacteristic* rxCharacteristic = service->createCharacteristic(
      RX_UUID,
      NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
  rxCharacteristic->setCallbacks(new RelayRxCallbacks());

  service->start();

  NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();
  NimBLEAdvertisementData advertisementData;
  NimBLEAdvertisementData scanResponseData;
  advertisementData.setName(DEVICE_NAME);
  advertisementData.addServiceUUID(SERVICE_UUID);
  scanResponseData.setName(DEVICE_NAME);
  advertising->setAdvertisementData(advertisementData);
  advertising->setScanResponseData(scanResponseData);
  advertising->addServiceUUID(SERVICE_UUID);
  advertising->enableScanResponse(true);
  advertising->start();
  Serial.printf("relay mode: %s, queue=%u, drain=%u ms\n",
                RELAY_USE_NOTIFY ? "notify" : "indicate",
                static_cast<unsigned int>(RELAY_QUEUE_CAPACITY),
                static_cast<unsigned int>(relayDrainIntervalMs()));
}

// Arduino setup initializes serial diagnostics and starts BLE advertising.
void setup() {
  Serial.begin(115200);
  delay(300);
  setupBleRelay();
  Serial.println("AirClip BLE relay advertising");
}

// The loop drains queued relay frames and yields to the BLE stack.
void loop() {
  drainRelayQueue();
  delay(2);
}
