package com.example.demo;

import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;

@Aspect
public class LoggingAspect {
    @Around("execution(* com.example.demo..*(..))")
    public Object trace() {
        return null;
    }
}
