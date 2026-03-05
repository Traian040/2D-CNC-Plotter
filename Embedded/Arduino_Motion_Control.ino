#include <math.h>
#include <Servo.h>

const int xStepPin = 2;
const int xDirPin = 5;
const int yStepPin = 3;
const int yDirPin = 6;
const int enablePin = 8;
const int servoPin = 11;

Servo zServo;
const int servoUpAngle = 90;
const int servoDownAngle = 50;
bool isPenDown = false;

const float stepsPerUnitX = 100.0;
const float stepsPerUnitY = 100.0;
const float masterAcceleration = 1500.0; 
const float masterMinStartSpeed = 200.0;
const float speedSlow = 500.0;
const float speedFast = 1500.0;

float gCurrentX = 0.0;
float gCurrentY = 0.0;

class StepperThread {
  private:
    int stepPin;
    int dirPin;
    long targetPosition;
    long currentPosition;
    unsigned long stepInterval;
    unsigned long lastStepTime;
    bool isRunning;
    float currentSpeed;
    float targetSpeed;
    float myAcceleration;
    
  public:
    StepperThread(int sPin, int dPin) {
      stepPin = sPin;
      dirPin = dPin;
      pinMode(stepPin, OUTPUT);
      pinMode(dirPin, OUTPUT);
      currentPosition = 0;
      isRunning = false;
    }
    
    void overwritePosition(long pos) {
      currentPosition = pos;
      isRunning = false;
    }
    
    void setTarget(long target, float maxSpeed, float accel, float startSpeed) {
      targetPosition = target;
      targetSpeed = maxSpeed;
      myAcceleration = accel;
      
      if (targetPosition > currentPosition) digitalWrite(dirPin, HIGH);
      else digitalWrite(dirPin, LOW);

      currentSpeed = startSpeed;
      if (currentSpeed > 0.1) stepInterval = 1000000.0 / currentSpeed;
      else stepInterval = 0;

      isRunning = (currentPosition != targetPosition);
      lastStepTime = micros();
    }

    bool update() {
      if (!isRunning) return false;
      if (currentPosition == targetPosition) {
        isRunning = false;
        return false;
      }
      unsigned long now = micros();
      if (now - lastStepTime >= stepInterval) {
        digitalWrite(stepPin, HIGH);
        delayMicroseconds(2); 
        digitalWrite(stepPin, LOW);
        lastStepTime = now;
        if (targetPosition > currentPosition) currentPosition++;
        else currentPosition--;
        if (currentSpeed < targetSpeed) {
          float timeSeconds = stepInterval / 1000000.0;
          currentSpeed += (myAcceleration * timeSeconds);
          if (currentSpeed > targetSpeed) currentSpeed = targetSpeed;
          if (currentSpeed > 0.1) stepInterval = 1000000.0 / currentSpeed;
        }
      }
      return true;
    }
    long getCurrentPosition() { return currentPosition; }
};

StepperThread threadX(xStepPin, xDirPin);
StepperThread threadY(yStepPin, yDirPin);

void moveTo(float targetX, float targetY, float moveSpeed) {
  long targetStepsX = (long)(targetX * stepsPerUnitX);
  long targetStepsY = (long)(targetY * stepsPerUnitY);
  long startStepsX = threadX.getCurrentPosition();
  long startStepsY = threadY.getCurrentPosition();
  long deltaX = abs(targetStepsX - startStepsX);
  long deltaY = abs(targetStepsY - startStepsY);
  if (deltaX == 0 && deltaY == 0) return;
  float speedX, speedY, accelX, accelY, startX, startY;
  float ratio;
  if (deltaX > deltaY) {
    ratio = (float)deltaY / deltaX;
    speedX = moveSpeed;
    accelX = masterAcceleration;
    startX = masterMinStartSpeed;
    speedY = moveSpeed * ratio;
    accelY = masterAcceleration * ratio;
    startY = masterMinStartSpeed * ratio;
  } else {
    ratio = (float)deltaX / deltaY;
    speedY = moveSpeed;
    accelY = masterAcceleration;
    startY = masterMinStartSpeed;
    speedX = moveSpeed * ratio;
    accelX = masterAcceleration * ratio;
    startX = masterMinStartSpeed * ratio;
  }
  threadX.setTarget(targetStepsX, speedX, accelX, startX);
  threadY.setTarget(targetStepsY, speedY, accelY, startY);
  while (threadX.update() | threadY.update()) { }
  gCurrentX = targetX;
  gCurrentY = targetY;
}

void arcMove(float targetX, float targetY, float i, float j, bool isClockwise, float speed) {
  float centerX = gCurrentX + i;
  float centerY = gCurrentY + j;
  float radius = sqrt(i*i + j*j);
  
  float startAngle = atan2(-j, -i);
  float endAngle = atan2(targetY - centerY, targetX - centerX);

  if (isClockwise && endAngle >= startAngle) endAngle -= 2 * PI;
  if (!isClockwise && endAngle <= startAngle) endAngle += 2 * PI;

  float totalAngle = fabs(endAngle - startAngle);
  int segments = ceil(totalAngle * radius * 5);

  for (int s = 1; s <= segments; s++) {
    float currentAngle = startAngle + (endAngle - startAngle) * ((float)s / segments);
    float nextX = centerX + radius * cos(currentAngle);
    float nextY = centerY + radius * sin(currentAngle);
    moveTo(nextX, nextY, speed);
  }
}
void doGToggle() {
  if (isPenDown) {
    zServo.write(servoUpAngle);
    Serial.println("Action: Pen UP");
    isPenDown = false;
  } else {
    zServo.write(servoDownAngle);
    Serial.println("Action: Pen DOWN");
    isPenDown = true;
  }
  delay(300);
}
  
float getValue(String line, char key, float defaultValue) {
  int index = line.indexOf(key);
  if (index == -1) return defaultValue;
  return line.substring(index + 1).toFloat();
}

void parseGcode(String line) {
  line.toUpperCase();
  line.trim();
  if (line.length() == 0) return;
  int comm = -1;
  if (line.startsWith("G0")) comm = 0;
  else if (line.startsWith("G1")) comm = 1;
  else if (line.startsWith("G2")) comm = 2;
  else if (line.startsWith("G3")) comm = 3;
  else if (line.startsWith("GTOGGLE") || line.startsWith("GT")) comm = 4;
  else {
    Serial.println("Error: Unsupported command");
    return;
  }
  float targetX = getValue(line, 'X', gCurrentX);
  float targetY = getValue(line, 'Y', gCurrentY);
  float valI = getValue(line, 'I', 0.0);
  float valJ = getValue(line, 'J', 0.0);
  switch(comm) {
    case 0: moveTo(targetX, targetY, speedSlow); break;
    case 1: moveTo(targetX, targetY, speedFast); break;
    case 2: arcMove(targetX, targetY, valI, valJ, true, speedFast); break;
    case 3: arcMove(targetX, targetY, valI, valJ, false, speedFast); break;
    case 4: doGToggle(); break;
  }
  Serial.println("Done.");
}

void setup() {
  Serial.begin(9600);
  pinMode(enablePin, OUTPUT);
  digitalWrite(enablePin, LOW);
  zServo.attach(servoPin);
  zServo.write(servoUpAngle);
  Serial.println("CNC Ready");
  isPenDown = false;
  gCurrentX = 0.0;
  gCurrentY = 0.0;
}

String inputString = "";
boolean stringComplete = false;

void loop() {
  while (Serial.available()) {
    char inChar = (char)Serial.read();
    if (inChar == '\n' || inChar == '\r') {
      if (inputString.length() > 0) stringComplete = true;
    } else {
      inputString += inChar;
    }
  }
  if (stringComplete) {
    parseGcode(inputString);
    inputString = "";
    stringComplete = false;
  }
}