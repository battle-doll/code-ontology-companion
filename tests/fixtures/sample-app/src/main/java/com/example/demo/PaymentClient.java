package com.example.demo;

public interface PaymentClient {
    Receipt charge(Order order);
}
