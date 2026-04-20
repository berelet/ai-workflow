#!/usr/bin/env python3
import re
import sys
import os

# Добавляем путь к проекту
sys.path.append('/home/aimchn/Desktop/Comfy/Multi Agent System/comfy-agents/comfy-agents')

from orchestrator.classification.pattern_detector import get_pattern_detector

def test_ac():
    detector = get_pattern_detector()
    results = []
    
    # AC1: Тестовые запросы для product-agent
    ac1_tests = [
        "Підбери товар - мені потрібен роутер для дому",
        "Подбери мне ноутбук для работы", 
        "Вибери телефон до 10000",
        "Выбери хороший пылесос"
    ]
    
    # AC3: Регрессия FAQ
    faq_tests = [
        "Які зараз активні акції?",
        "Товар дня"
    ]
    
    # AC4: Регрессия customers
    customers_tests = [
        "Мої бонуси"
    ]
    
    # Дополнительный тест product (не затронут)
    product_tests = [
        "Покажи ноутбуки"
    ]
    
    print("=== AC1: Product Selection Tests ===")
    ac1_pass = True
    for test in ac1_tests:
        pattern, agent, score = detector.detect_pattern(test)
        expected = "product"
        status = "PASS" if agent == expected else "FAIL"
        if agent != expected:
            ac1_pass = False
        print(f"'{test}' -> {agent} (expected: {expected}) - {status}")
        results.append(f"AC1 Test: '{test}' -> {agent} (expected: {expected}) - {status}")
    
    print(f"\nAC1 Overall: {'PASS' if ac1_pass else 'FAIL'}")
    results.append(f"AC1 Overall: {'PASS' if ac1_pass else 'FAIL'}")
    
    print("\n=== AC3: FAQ Regression Tests ===")
    ac3_pass = True
    for test in faq_tests:
        pattern, agent, score = detector.detect_pattern(test)
        expected = "faq"
        status = "PASS" if agent == expected else "FAIL"
        if agent != expected:
            ac3_pass = False
        print(f"'{test}' -> {agent} (expected: {expected}) - {status}")
        results.append(f"AC3 Test: '{test}' -> {agent} (expected: {expected}) - {status}")
    
    print(f"\nAC3 Overall: {'PASS' if ac3_pass else 'FAIL'}")
    results.append(f"AC3 Overall: {'PASS' if ac3_pass else 'FAIL'}")
    
    print("\n=== AC4: Customers Regression Tests ===")
    ac4_pass = True
    for test in customers_tests:
        pattern, agent, score = detector.detect_pattern(test)
        expected = "customers"
        status = "PASS" if agent == expected else "FAIL"
        if agent != expected:
            ac4_pass = False
        print(f"'{test}' -> {agent} (expected: {expected}) - {status}")
        results.append(f"AC4 Test: '{test}' -> {agent} (expected: {expected}) - {status}")
    
    print(f"\nAC4 Overall: {'PASS' if ac4_pass else 'FAIL'}")
    results.append(f"AC4 Overall: {'PASS' if ac4_pass else 'FAIL'}")
    
    print("\n=== Additional Product Tests ===")
    for test in product_tests:
        pattern, agent, score = detector.detect_pattern(test)
        expected = "product"
        status = "PASS" if agent == expected else "FAIL"
        print(f"'{test}' -> {agent} (expected: {expected}) - {status}")
        results.append(f"Additional Test: '{test}' -> {agent} (expected: {expected}) - {status}")
    
    # AC2: Проверка regex напрямую
    print("\n=== AC2: Regex Pattern Check ===")
    product_pattern = r'\b(підібрати|подобрать|вибрати|выбрать|порекомендуй|порадь|посоветуй|підбери|подбери|выбери|вибери)\b'
    
    ac2_tests = [
        "підбери",
        "подбери", 
        "выбери",
        "вибери"
    ]
    
    ac2_pass = True
    for test in ac2_tests:
        match = re.search(product_pattern, test.lower())
        status = "PASS" if match else "FAIL"
        if not match:
            ac2_pass = False
        print(f"Regex test '{test}' - {status}")
        results.append(f"AC2 Regex: '{test}' - {status}")
    
    print(f"\nAC2 Overall: {'PASS' if ac2_pass else 'FAIL'}")
    results.append(f"AC2 Overall: {'PASS' if ac2_pass else 'FAIL'}")
    
    return results

if __name__ == "__main__":
    results = test_ac()